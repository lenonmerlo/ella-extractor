from __future__ import annotations

import logging
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any

import pdfplumber
from fastapi import FastAPI, File, HTTPException, Response, UploadFile

from parsers.itau_personnalite import parse_itau_personnalite as parse_itau_personnalite_text
from parsers.sicredi import parse_sicredi


app = FastAPI(title="ELLA PDF Extractor (Local Test Service)")


logger = logging.getLogger("ella-extractor")


def _looks_like_pdf(pdf_bytes: bytes) -> bool:
    if not pdf_bytes:
        return False
    # Cheap heuristics: PDF header + EOF marker (some PDFs have whitespace after EOF).
    if not pdf_bytes.startswith(b"%PDF-"):
        return False
    tail = pdf_bytes[-2048:] if len(pdf_bytes) > 2048 else pdf_bytes
    return b"%%EOF" in tail


_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def clean_extracted_text(text: str) -> str:
    """Clean per-page extracted text without breaking line layout.

    - Removes (cid:N) tokens
    - Normalizes spaces/tabs inside lines
    - Preserves newlines
    """
    if not text:
        return ""

    # Keep line breaks, just normalize within lines.
    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # Remove PDF glyph artifacts
    text = _CID_TOKEN_RE.sub("", text)

    # Normalize spacing within each line (do NOT collapse newlines)
    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line)
        # Optional: trim per line but keep empty lines
        cleaned_lines.append(line.strip())

    return "\n".join(cleaned_lines)


def _looks_glued(text: str) -> bool:
    if not text:
        return True

    # Heuristic: if very few spaces and many long alpha runs, the extraction likely "glued" words.
    spaces = text.count(" ")
    letters = sum(1 for ch in text if ch.isalpha())
    if letters > 200 and spaces / max(1, len(text)) < 0.01:
        return True

    if re.search(r"[A-Za-zÀ-ÿ]{18,}", text):
        # e.g. "ResumodafaturaemR$" or similar
        return True

    # Example of two dd/MM transactions ending up in one line
    if re.search(r"\b\d{2}/\d{2}.*\b\d{2}/\d{2}\b", text):
        return True

    return False


def _extract_words_compat(page: Any) -> list[dict[str, Any]]:
    # pdfplumber versions vary; use the best parameters available.
    try:
        return page.extract_words(keep_blank_chars=False, use_text_flow=True)
    except TypeError:
        return page.extract_words(keep_blank_chars=False)


def _reconstruct_text_from_words(page: Any, y_tolerance: float = 3.0) -> str:
    """Fallback reconstruction using words + coordinates.

    This is a pragmatic fallback when extract_text() produces "glued" output.
    We group words into lines by their `top` coordinate (within tolerance),
    sort by `x0`, then join with spaces. This tends to preserve visual layout
    well enough to keep transactions on separate lines.
    """

    words = _extract_words_compat(page)
    if not words:
        return ""

    words_sorted = sorted(words, key=lambda w: (float(w.get("top", 0.0)), float(w.get("x0", 0.0))))

    lines: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_top: float | None = None

    for w in words_sorted:
        top = float(w.get("top", 0.0))
        if current_top is None:
            current_top = top
            current = [w]
            continue

        if abs(top - current_top) <= y_tolerance:
            current.append(w)
        else:
            lines.append(current)
            current_top = top
            current = [w]

    if current:
        lines.append(current)

    out_lines: list[str] = []
    for line_words in lines:
        line_words = sorted(line_words, key=lambda w: float(w.get("x0", 0.0)))
        parts: list[str] = []
        for w in line_words:
            t = str(w.get("text", "")).strip()
            if t:
                parts.append(t)
        out_lines.append(" ".join(parts))

    return "\n".join(out_lines)


def extract_page_text(page: Any) -> tuple[str, str]:
    """Extract text from one page, preferring layout-preserving methods."""

    # 1) Try layout extraction when supported.
    layout_text: str | None = None
    try:
        layout_text = page.extract_text(layout=True, x_tolerance=2, y_tolerance=2)
    except TypeError:
        layout_text = None

    if layout_text:
        layout_text = clean_extracted_text(layout_text)
        if not _looks_glued(layout_text):
            return layout_text, "layout"

    # 2) Fallback: word-based reconstruction.
    words_text = _reconstruct_text_from_words(page)
    words_text = clean_extracted_text(words_text)
    if words_text:
        return words_text, "words"

    # 3) Last fallback: plain extract_text.
    plain = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
    plain = clean_extracted_text(plain)
    return plain, "plain"


def _text_debug_stats(text: str) -> tuple[int, float, list[str]]:
    lines = text.split("\n") if text else []
    line_count = len(lines)
    non_empty = [ln for ln in lines if ln.strip()]
    avg = (sum(len(ln) for ln in non_empty) / len(non_empty)) if non_empty else 0.0
    sample = [ln for ln in lines[:20]]
    return line_count, float(avg), sample


def normalize_extracted_text(text: str) -> str:
    if not text:
        return ""

    # 1) Non-breaking spaces -> regular space
    text = text.replace("\u00a0", " ").replace("\xa0", " ")

    # 2) Normalize line endings
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    # 3) Collapse multiple spaces/tabs
    text = re.sub(r"[ \t]{2,}", " ", text)

    # 4) Trim trailing spaces per-line (keeps indentation minimal, avoids bloating)
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    # 5) Remove excessive blank lines
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/version")
def version() -> dict[str, str]:
    return {
        "name": "ella-extractor",
        "version": os.getenv("VERSION", "dev"),
        "gitSha": os.getenv("GIT_SHA", "unknown"),
        "buildTime": os.getenv("BUILD_TIME", "unknown"),
    }


@app.post("/extract/itau-personnalite")
async def extract_itau_personnalite(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[extract/itau-personnalite] filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(pdf_bytes) if pdf_bytes else 0,
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    notes: list[str] = []
    page_texts: list[str] = []
    methods_used: list[str] = []

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                extracted, method = extract_page_text(page)
                methods_used.append(method)
                page_texts.append(extracted)
    except Exception as exc:  # pragma: no cover
        notes.append(f"pdfplumber_error:{type(exc).__name__}")
        if _looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=422, detail={"reason": "UNREADABLE_PDF", "message": "Failed to read PDF"})
        raise HTTPException(status_code=400, detail="Failed to read PDF")

    full_text = normalize_extracted_text("\n\n".join(page_texts))

    line_count, avg_chars, sample = _text_debug_stats(full_text)
    method_used: str
    unique_methods = sorted(set(methods_used))
    if len(unique_methods) == 1:
        method_used = unique_methods[0]
    else:
        method_used = "mixed:" + "+".join(unique_methods)

    return {
        "bank": "itau_personnalite",
        "filename": file.filename,
        "pages": pages,
        "textLength": len(full_text),
        "text": full_text,
        "meta": {
            "engine": "pdfplumber",
            "notes": notes,
            "methodUsed": method_used,
            "lineCount": line_count,
            "avgCharsPerLine": avg_chars,
            "sample": sample,
        },
    }


@app.post("/parse/itau-personnalite")
async def parse_itau_personnalite(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[parse/itau-personnalite] filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(pdf_bytes) if pdf_bytes else 0,
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    page_texts: list[str] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                extracted, _method = extract_page_text(page)
                page_texts.append(extracted)
    except Exception:
        if _looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=422, detail={"reason": "UNREADABLE_PDF", "message": "Failed to read PDF"})
        raise HTTPException(status_code=400, detail="Failed to read PDF")

    raw_text = "\n\n".join(page_texts)

    fixture_path = Path(__file__).resolve().parent / "tests" / "fixtures" / "itau_personnalite_reference.txt"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(raw_text, encoding="utf-8")

    result, warnings, debug = parse_itau_personnalite_text(raw_text)
    if not result.get("transactions"):
        result["reason"] = "UNSUPPORTED_LAYOUT"
    # include filename for convenience in local testing
    result["filename"] = file.filename
    return result


@app.post("/parse/sicredi")
async def parse_sicredi_invoice(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Recebe um PDF da fatura Sicredi, extrai o texto e retorna dados estruturados."""
    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[parse/sicredi] filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(pdf_bytes) if pdf_bytes else 0,
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    page_texts: list[str] = []
    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                extracted, _method = extract_page_text(page)
                page_texts.append(extracted)
    except Exception:
        if _looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=422, detail={"reason": "UNREADABLE_PDF", "message": "Failed to read PDF"})
        raise HTTPException(status_code=400, detail="Failed to read PDF")

    raw_text = "\n\n".join(page_texts)

    # Save raw text fixture for reproducible debugging/tests (same approach as Itaú Personalité).
    fixture_path = Path(__file__).resolve().parent / "tests" / "fixtures" / "sicredi_reference.txt"
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(raw_text, encoding="utf-8")

    result = parse_sicredi(raw_text)

    if not result.get("transactions"):
        result["reason"] = "UNSUPPORTED_LAYOUT"
    result["filename"] = file.filename
    return result
