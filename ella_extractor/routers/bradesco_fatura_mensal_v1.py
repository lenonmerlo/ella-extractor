from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from parsers.bradesco_fatura_mensal_v1 import (
    parse_bradesco_fatura_mensal_v1 as parse_bradesco_fatura_mensal_v1_text,
)

from ella_extractor.services.fixtures import write_text_fixture
from ella_extractor.services.pdf_extraction import (
    extract_pdf_pages_text,
    looks_like_pdf,
    normalize_extracted_text,
    text_debug_stats,
)


router = APIRouter()
logger = logging.getLogger("ella-extractor")


@router.post("/extract/bradesco-fatura-mensal-v1")
async def extract_bradesco_fatura_mensal_v1(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[extract/bradesco-fatura-mensal-v1] filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(pdf_bytes) if pdf_bytes else 0,
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    notes: list[str] = []
    try:
        pages, page_texts, methods_used = extract_pdf_pages_text(pdf_bytes)
    except Exception as exc:  # pragma: no cover
        notes.append(f"pdfplumber_error:{type(exc).__name__}")
        if looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=422, detail={"reason": "UNREADABLE_PDF", "message": "Failed to read PDF"})
        raise HTTPException(status_code=400, detail="Failed to read PDF")

    full_text = normalize_extracted_text("\n\n".join(page_texts))

    line_count, avg_chars, sample = text_debug_stats(full_text)
    unique_methods = sorted(set(methods_used))
    if len(unique_methods) == 1:
        method_used = unique_methods[0]
    else:
        method_used = "mixed:" + "+".join(unique_methods)

    return {
        "bank": "bradesco_fatura_mensal_v1",
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


@router.post("/parse/bradesco-fatura-mensal-v1")
async def parse_bradesco_fatura_mensal_v1(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[parse/bradesco-fatura-mensal-v1] filename=%s content_type=%s bytes=%d",
        file.filename,
        file.content_type,
        len(pdf_bytes) if pdf_bytes else 0,
    )
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="Empty file")

    try:
        _pages, page_texts, _methods = extract_pdf_pages_text(pdf_bytes)
    except Exception:
        if looks_like_pdf(pdf_bytes):
            raise HTTPException(status_code=422, detail={"reason": "UNREADABLE_PDF", "message": "Failed to read PDF"})
        raise HTTPException(status_code=400, detail="Failed to read PDF")

    raw_text = "\n\n".join(page_texts)

    base_dir = Path(__file__).resolve().parents[2]  # extractor/
    write_text_fixture(filename="bradesco_fatura_mensal_v1_reference.txt", raw_text=raw_text, base_dir=base_dir)

    result, _warnings, _debug = parse_bradesco_fatura_mensal_v1_text(raw_text)
    if not result.get("transactions"):
        result["reason"] = "UNSUPPORTED_LAYOUT"

    result["filename"] = file.filename
    return result
