from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, Response, UploadFile

from parsers.itau_bank_statement import parse_itau_bank_statement as parse_itau_bank_statement_text

from ella_extractor.services.fixtures import write_text_fixture
from ella_extractor.services.pdf_extraction import extract_pdf_pages_text, looks_like_pdf


router = APIRouter()
logger = logging.getLogger("ella-extractor")


@router.post("/parse/itau-bank-statement")
async def parse_itau_bank_statement(
    response: Response,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Recebe um PDF de extrato bancário Itaú (conta corrente), extrai o texto e retorna dados estruturados."""

    response.headers["X-Parser-Version"] = os.getenv("VERSION", "dev")
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Invalid content-type. Expected application/pdf")

    pdf_bytes = await file.read()
    logger.info(
        "[parse/itau-bank-statement] filename=%s content_type=%s bytes=%d",
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

    # Save reference text locally for fixture-based tests/debugging.
    base_dir = Path(__file__).resolve().parents[2]  # extractor/
    write_text_fixture(filename="itau_bank_statement_reference.txt", raw_text=raw_text, base_dir=base_dir)

    result, warnings, debug = parse_itau_bank_statement_text(raw_text)

    if warnings:
        result["warnings"] = warnings
    if debug:
        result["debug"] = debug

    if not result.get("transactions"):
        result["reason"] = result.get("reason") or "UNSUPPORTED_LAYOUT"

    result["filename"] = file.filename
    return result
