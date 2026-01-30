from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_parse_sicredi_rejects_non_pdf() -> None:
    files = {"file": ("not-a-pdf.txt", b"hello", "text/plain")}
    r = client.post("/parse/sicredi", files=files)
    assert r.status_code == 400


def test_parse_sicredi_returns_structured_data_when_fixture_pdf_exists() -> None:
    # Optional integration test: if you add a real Sicredi PDF here, we validate the endpoint.
    pdf_path = Path(__file__).parent / "Sicredi_Reference.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Missing test PDF: {pdf_path}")

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        r = client.post("/parse/sicredi", files=files)

    assert r.status_code == 200
    payload = r.json()

    assert payload["bank"] == "SICREDI"
    assert payload.get("dueDate")
    assert payload.get("total") is not None
    assert isinstance(payload.get("transactions"), list)
