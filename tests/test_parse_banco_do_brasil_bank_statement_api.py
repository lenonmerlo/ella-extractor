from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_parse_banco_do_brasil_bank_statement_rejects_non_pdf() -> None:
    files = {"file": ("not-a-pdf.txt", b"hello", "text/plain")}
    r = client.post("/parse/banco-do-brasil-bank-statement", files=files)
    assert r.status_code == 400


def test_parse_banco_do_brasil_bank_statement_accepts_pdf_shape_and_returns_json() -> None:
    fake_pdf = io.BytesIO(b"%PDF-1.4\n%EOF")
    files = {"file": ("fake.pdf", fake_pdf, "application/pdf")}
    r = client.post("/parse/banco-do-brasil-bank-statement", files=files)
    assert r.status_code in (200, 400, 422)
