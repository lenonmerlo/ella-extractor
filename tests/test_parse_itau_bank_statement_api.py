from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_parse_itau_bank_statement_api_with_fixture_pdf_if_present() -> None:
    pdf_path = Path(__file__).parent / "fixtures" / "itau_extrato_102025.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Missing test PDF: {pdf_path}")

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        r = client.post("/parse/itau-bank-statement", files=files)

    assert r.status_code == 200
    payload = r.json()

    assert payload["bank"] == "ITAU"
    assert payload.get("statementDate")
    assert isinstance(payload.get("transactions"), list)
    assert len(payload.get("transactions", [])) > 10
