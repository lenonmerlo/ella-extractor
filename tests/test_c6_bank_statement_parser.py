from __future__ import annotations

import pytest

from parsers.c6_bank_statement import parse_c6_bank_statement


def test_parse_c6_bank_statement_basic_table() -> None:
    raw = """
C6 BANK
Extrato
Período: 01/01/2026 a 31/01/2026

Data Descrição Valor Saldo
02/01 PIX RECEBIDO JOAO 150,00 1.150,00
03/01 COMPRA CARTAO -50,00 1.100,00
04/01 Saldo do dia 1.100,00
05/01 TED ENVIADA -100,00 1.000,00
""".strip()

    result, warnings, debug = parse_c6_bank_statement(raw)

    assert result["bank"] == "C6"
    assert result["statementDate"] == "2026-01-31"
    assert result["openingBalance"] == pytest.approx(1000.00)
    assert result["closingBalance"] == pytest.approx(1000.00)

    txs = result["transactions"]
    assert len(txs) >= 3

    # First real transaction
    assert txs[0]["transactionDate"] == "2026-01-02"
    assert txs[0]["type"] == "CREDIT"
    assert txs[0]["amount"] == pytest.approx(150.00)
    assert txs[0]["balance"] == pytest.approx(1150.00)

    # A debit should be negative
    debit = next(t for t in txs if t["transactionDate"] == "2026-01-03")
    assert debit["type"] == "DEBIT"
    assert debit["amount"] == pytest.approx(-50.00)

    # Balance line must be marked BALANCE and amount 0
    bal = next(t for t in txs if t["transactionDate"] == "2026-01-04")
    assert bal["type"] == "BALANCE"
    assert bal["amount"] == pytest.approx(0.00)
    assert bal["balance"] == pytest.approx(1100.00)

    assert "not_c6" not in warnings
    assert debug.get("txCount", 0) >= 3


def test_parse_c6_bank_statement_rejects_non_c6() -> None:
    raw = "Extrato do Banco X\nPeríodo: 01/01/2026 a 31/01/2026\n01/01 TESTE 10,00 10,00"
    result, warnings, _debug = parse_c6_bank_statement(raw)
    assert result["reason"] == "UNSUPPORTED_LAYOUT"
    assert warnings and warnings[0] == "not_c6"


def test_parse_c6_bank_statement_detects_debit_and_credit_from_currency_marker() -> None:
    # Some C6 statement layouts place a currency marker just before the amount.
    # Debit: "-R$"; Credit: "R$".
    raw = """
C6 BANK
Extrato
Período: 01/01/2026 a 31/01/2026

Data Descrição Valor Saldo
02/01 Outros gastos VIVO-ES -R$ 59,00 941,00
19/01 Entrada PIX Pix recebido de LENON R$ 6.500,00 7.441,00
""".strip()

    result, warnings, _debug = parse_c6_bank_statement(raw)

    assert "not_c6" not in warnings
    assert result["bank"] == "C6"
    assert result["statementDate"] == "2026-01-31"

    txs = result["transactions"]
    assert len(txs) == 2

    debit = next(t for t in txs if t["transactionDate"] == "2026-01-02")
    assert debit["type"] == "DEBIT"
    assert debit["amount"] == pytest.approx(-59.00)
    assert "-R$" not in debit["description"]

    credit = next(t for t in txs if t["transactionDate"] == "2026-01-19")
    assert credit["type"] == "CREDIT"
    assert credit["amount"] == pytest.approx(6500.00)
    assert credit["balance"] == pytest.approx(7441.00)
    assert credit["description"].endswith("R$") is False


def test_parse_c6_bank_statement_uses_last_saldo_do_dia_as_closing_balance() -> None:
    raw = """
C6 BANK
Extrato
Janeiro 2026 (01/01/2026 - 24/01/2026)

02/01 Outros gastos VIVO-ES -R$ 59,00
Saldo do dia 02/01/26 R$ 1.869,92

21/01 Saída PIX Pix enviado para NIC. BR -R$ 40,00
Saldo do dia 21/01/26 R$ 1.484,06
""".strip()

    result, warnings, debug = parse_c6_bank_statement(raw)

    assert "not_c6" not in warnings
    assert result["bank"] == "C6"
    assert result["statementDate"] == "2026-01-24"
    assert debug.get("txCount", 0) >= 3

    # Opening balance should be derived from the first saldo-do-dia of the period.
    # saldo(02/01) = 1869.92 and dayNet(02/01) = -59.00 => opening = 1928.92
    assert result["openingBalance"] == pytest.approx(1928.92)

    # The closing balance should come from the last explicit "Saldo do dia" row.
    assert result["closingBalance"] == pytest.approx(1484.06)

    # Ensure the balance rows are actually extracted.
    balance_rows = [t for t in result["transactions"] if t["type"] == "BALANCE"]
    assert len(balance_rows) >= 2
