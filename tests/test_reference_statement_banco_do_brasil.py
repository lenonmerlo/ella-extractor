from __future__ import annotations

from pathlib import Path

import pytest

from parsers.banco_do_brasil_bank_statement import parse_banco_do_brasil_bank_statement


def test_reference_statement_banco_do_brasil() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "banco_do_brasil_bank_statement_reference.txt"
    assert fixture_path.exists()

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, warnings, debug = parse_banco_do_brasil_bank_statement(text)

    assert "not_banco_do_brasil" not in warnings
    assert result["bank"] == "BANCO_DO_BRASIL"
    assert result["statementDate"] == "2026-01-31"
    assert result["openingBalance"] == pytest.approx(850.00)
    assert result["closingBalance"] == pytest.approx(899.80)

    txs = result.get("transactions", [])
    non_balance = [t for t in txs if t.get("type") != "BALANCE"]
    assert len(non_balance) >= 5

    for tx in non_balance:
        amount = float(tx.get("amount") or 0)
        if tx.get("type") == "DEBIT":
            assert amount <= 0
        if tx.get("type") == "CREDIT":
            assert amount >= 0

    assert result.get("reason") != "UNSUPPORTED_LAYOUT"
    assert isinstance(warnings, list)
    assert isinstance(debug, dict)
