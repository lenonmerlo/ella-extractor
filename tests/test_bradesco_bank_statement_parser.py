from __future__ import annotations

import pytest

from parsers.bradesco_bank_statement import parse_bradesco_bank_statement


def test_parse_bradesco_bank_statement_basic_table() -> None:
    raw = """
BANCO BRADESCO
Extrato
Extrato de: Agência: 2000 | Conta: 161404-5 | Movimentação entre: 12/12/2025 e 09/02/2026

Data Histórico Crédito Débito Saldo
30/12/2025 RECEBIMENTO FORNECEDOR 3002000 16.007,54 16.007,54
PLANO DE BENEFICIOS III
TRANSFERENCIA PIX
1700359 16.007,54 0,00
DES: Virginia Mara Rangel 30/12
""".strip()

    result, warnings, debug = parse_bradesco_bank_statement(raw)

    assert "not_bradesco" not in warnings
    assert result["bank"] == "BRADESCO"
    assert result["statementDate"] == "2026-02-09"

    assert result["openingBalance"] == pytest.approx(0.00)
    assert result["closingBalance"] == pytest.approx(0.00)

    txs = [t for t in result["transactions"] if t["type"] != "BALANCE"]
    assert len(txs) >= 2

    credit = next(t for t in txs if t["transactionDate"] == "2025-12-30" and t["type"] == "CREDIT")
    assert credit["amount"] == pytest.approx(16007.54)
    assert credit["balance"] == pytest.approx(16007.54)

    debit = next(t for t in txs if t["transactionDate"] == "2025-12-30" and t["type"] == "DEBIT")
    assert debit["amount"] == pytest.approx(-16007.54)
    assert debit["balance"] == pytest.approx(0.00)
    assert "DES:" in debit["description"]

    assert debug.get("txCount", 0) >= 2


def test_parse_bradesco_bank_statement_rejects_non_bradesco() -> None:
    raw = "Extrato do Banco X\nPeríodo: 01/01/2026 a 31/01/2026\n01/01 TESTE 10,00 10,00"
    result, warnings, _debug = parse_bradesco_bank_statement(raw)
    assert result["reason"] == "UNSUPPORTED_LAYOUT"
    assert warnings and warnings[0] == "not_bradesco"
