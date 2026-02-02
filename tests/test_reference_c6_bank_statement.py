from __future__ import annotations

from pathlib import Path

import pytest

from parsers.c6_bank_statement import parse_c6_bank_statement


def test_reference_c6_bank_statement_fixture() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "c6_bank_statement_reference.txt"
    raw = fixture_path.read_text(encoding="utf-8")

    result, warnings, debug = parse_c6_bank_statement(raw)

    assert "not_c6" not in warnings
    assert result["bank"] == "C6"

    # Fixture states statement period ends on 24/01/2026.
    assert result["statementDate"] == "2026-01-24"

    # These are the balances shown in the fixture's "Saldo do dia" rows.
    assert result["openingBalance"] == pytest.approx(1928.92)
    assert result["closingBalance"] == pytest.approx(1484.06)

    txs = result["transactions"]
    assert len(txs) >= 10

    # Expect 6 real transactions and multiple BALANCE rows.
    non_balance = [t for t in txs if t["type"] != "BALANCE"]
    balance_rows = [t for t in txs if t["type"] == "BALANCE"]
    assert len(non_balance) == 6
    assert len(balance_rows) >= 5

    # Sanity-check signs.
    credits = [t for t in non_balance if t["type"] == "CREDIT"]
    debits = [t for t in non_balance if t["type"] == "DEBIT"]
    assert len(credits) == 1
    assert len(debits) == 5

    assert credits[0]["amount"] == pytest.approx(6500.00)
    assert all(t["amount"] < 0 for t in debits)

    # Debug should confirm we derived opening from the first "Saldo do dia".
    assert debug.get("openingDerivedFromSaldoDoDia")
    assert debug["openingDerivedFromSaldoDoDia"]["date"] == "2026-01-02"
