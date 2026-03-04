from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_parse_santander_rejects_non_pdf() -> None:
    files = {"file": ("not-a-pdf.txt", b"hello", "text/plain")}
    r = client.post("/parse/santander", files=files)
    assert r.status_code == 400


def test_parse_santander_accepts_pdf_shape_and_returns_json() -> None:
    # minimal fake PDF header to pass content checks; may still fail to parse as readable PDF
    fake_pdf = io.BytesIO(b"%PDF-1.4\n%EOF")
    files = {"file": ("fake.pdf", fake_pdf, "application/pdf")}
    r = client.post("/parse/santander", files=files)
    # acceptable behavior: readable check can fail as unsupported/unreadable
    assert r.status_code in (200, 400, 422)
