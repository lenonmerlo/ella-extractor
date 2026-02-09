from __future__ import annotations

from pathlib import Path

import pytest

from parsers.bradesco_bank_statement import parse_bradesco_bank_statement


def test_reference_statement_bradesco() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "bradesco_bank_statement_reference.txt"
    assert fixture_path.exists()

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, warnings, debug = parse_bradesco_bank_statement(text)

    assert "not_bradesco" not in warnings
    assert result["bank"] == "BRADESCO"
    assert result["statementDate"] == "2026-02-09"
    assert result["openingBalance"] == pytest.approx(0.00)
    assert result["closingBalance"] == pytest.approx(0.00)

    txs = result.get("transactions", [])
    non_balance = [t for t in txs if t.get("type") != "BALANCE"]
    assert len(non_balance) >= 8

    # Should not swallow footer into last tx.
    assert all("Total" not in (t.get("description") or "") for t in non_balance)

    # Spot-check the known pair on 30/12.
    d3012 = [t for t in non_balance if t.get("transactionDate") == "2025-12-30"]
    assert len(d3012) >= 2
    assert any(t.get("type") == "CREDIT" and float(t.get("amount") or 0) == pytest.approx(16007.54) for t in d3012)
    assert any(t.get("type") == "DEBIT" and float(t.get("amount") or 0) == pytest.approx(-16007.54) for t in d3012)

    # Contract: amount sign matches type
    for tx in non_balance:
        amount = float(tx.get("amount") or 0)
        if tx.get("type") == "DEBIT":
            assert amount <= 0
        if tx.get("type") == "CREDIT":
            assert amount >= 0

    assert result.get("reason") != "UNSUPPORTED_LAYOUT"
    assert isinstance(warnings, list)
    assert isinstance(debug, dict)
