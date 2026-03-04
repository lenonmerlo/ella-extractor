from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from parsers.c6_invoice import parse_c6_invoice

from ella_extractor.services.fixtures import write_text_fixture
from ella_extractor.services.pdf_extraction import extract_pdf_pages_text, looks_like_pdf


router = APIRouter()
logger = logging.getLogger("ella-extractor")


@router.post("/parse/c6-invoice")
async def parse_c6_invoice_route(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Recebe um PDF da fatura C6, extrai texto e retorna dados estruturados."""

    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[parse/c6-invoice] filename=%s content_type=%s bytes=%d",
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
    write_text_fixture(filename="c6_invoice_reference.txt", raw_text=raw_text, base_dir=base_dir)

    result = parse_c6_invoice(raw_text)

    if not result.get("transactions"):
        result["reason"] = "UNSUPPORTED_LAYOUT"

    result["filename"] = file.filename
    return result
