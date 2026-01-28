from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_health() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_extract_itau_personnalite_valid_pdf() -> None:
    pdf_path = Path(__file__).parent / "Fatura_MASTERCARD_100408531929_12-2025.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Missing test PDF: {pdf_path}")

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        r = client.post("/extract/itau-personnalite", files=files)

    assert r.status_code == 200
    payload = r.json()
    assert payload["bank"] == "ITAU_PERSONNALITE"
    assert payload["filename"] == pdf_path.name
    assert payload["pages"] >= 1
    assert payload["text"]
    assert payload["textLength"] == len(payload["text"])
    assert payload["meta"]["engine"] == "pdfplumber"


def test_extract_itau_personnalite_rejects_non_pdf() -> None:
    files = {"file": ("not-a-pdf.txt", b"hello", "text/plain")}
    r = client.post("/extract/itau-personnalite", files=files)
    assert r.status_code == 400
