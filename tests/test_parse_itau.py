from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app


client = TestClient(app)


def test_health_ok() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_parse_itau_personnalite_returns_structured_data() -> None:
    pdf_path = Path(__file__).parent / "Fatura_MASTERCARD_100408531929_12-2025.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Missing test PDF: {pdf_path}")

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        r = client.post("/parse/itau-personnalite", files=files)

    assert r.status_code == 200
    payload = r.json()

    assert payload["bank"] == "itau_personnalite"
    assert payload.get("dueDate")
    assert payload.get("total") is not None
    assert isinstance(payload.get("transactions"), list)
    assert payload.get("debug", {}).get("transactionsCount", 0) > 0


def test_parse_itau_personnalite_does_not_include_future_invoice_lines() -> None:
    pdf_path = Path(__file__).parent / "Fatura_MASTERCARD_100408531929_12-2025.pdf"
    if not pdf_path.exists():
        pytest.skip(f"Missing test PDF: {pdf_path}")

    with pdf_path.open("rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}
        r = client.post("/parse/itau-personnalite", files=files)

    assert r.status_code == 200
    payload = r.json()

    txs = payload.get("transactions", [])
    assert txs

    # Guarantee we didn't accidentally parse the summary lines like "Próxima fatura 979,90"
    for tx in txs:
        desc = (tx.get("description") or "").lower()
        assert "proxima fatura" not in desc
        assert "próxima fatura" not in desc
        amount = float(tx.get("amount"))
        assert abs(amount - 979.90) > 0.001
