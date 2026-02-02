from __future__ import annotations

import re
from io import BytesIO
from typing import Any

import pdfplumber


_CID_TOKEN_RE = re.compile(r"\(cid:\d+\)")


def looks_like_pdf(pdf_bytes: bytes) -> bool:
    if not pdf_bytes:
        return False
    # Cheap heuristics: PDF header + EOF marker (some PDFs have whitespace after EOF).
    if not pdf_bytes.startswith(b"%PDF-"):
        return False
    tail = pdf_bytes[-2048:] if len(pdf_bytes) > 2048 else pdf_bytes
    return b"%%EOF" in tail


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
        cleaned_lines.append(line.strip())

    return "\n".join(cleaned_lines)


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


def text_debug_stats(text: str) -> tuple[int, float, list[str]]:
    lines = text.split("\n") if text else []
    line_count = len(lines)
    non_empty = [ln for ln in lines if ln.strip()]
    avg = (sum(len(ln) for ln in non_empty) / len(non_empty)) if non_empty else 0.0
    sample = [ln for ln in lines[:20]]
    return line_count, float(avg), sample


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

    Pragmatic fallback when extract_text() produces "glued" output.
    We group words into lines by their `top` coordinate (within tolerance),
    sort by `x0`, then join with spaces.
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


def extract_pdf_pages_text(pdf_bytes: bytes) -> tuple[int, list[str], list[str]]:
    """Return (pages_count, page_texts, methods_used)."""

    page_texts: list[str] = []
    methods_used: list[str] = []

    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            extracted, method = extract_page_text(page)
            methods_used.append(method)
            page_texts.append(extracted)

    return pages, page_texts, methods_used
