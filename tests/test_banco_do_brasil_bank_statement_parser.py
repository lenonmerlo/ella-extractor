from __future__ import annotations

import pytest

from parsers.banco_do_brasil_bank_statement import parse_banco_do_brasil_bank_statement


def test_parse_banco_do_brasil_bank_statement_basic() -> None:
    raw = """
BANCO DO BRASIL
Extrato de Conta Corrente
Período: 01/01/2026 a 31/01/2026
Dia Lote Documento Histórico Valor
02 0000 12345 PIX RECEBIDO JOAO 1.200,00 C
02 0000 12346 PAGAMENTO CARTAO VISA 350,00 D
02 Saldo do dia 850,00 C
03 0000 22345 TARIFA MENSALIDADE 15,90 D
03 Saldo do dia 834,10 C
""".strip()

    result, warnings, debug = parse_banco_do_brasil_bank_statement(raw)

    assert "not_banco_do_brasil" not in warnings
    assert result["bank"] == "BANCO_DO_BRASIL"
    assert result["statementDate"] == "2026-01-31"
    assert result["openingBalance"] == pytest.approx(850.00)
    assert result["closingBalance"] == pytest.approx(834.10)

    txs = result["transactions"]
    non_balance = [t for t in txs if t["type"] != "BALANCE"]
    assert len(non_balance) >= 3

    credit = next(t for t in non_balance if "PIX RECEBIDO" in t["description"])
    assert credit["type"] == "CREDIT"
    assert credit["amount"] == pytest.approx(1200.00)

    debit = next(t for t in non_balance if "PAGAMENTO CARTAO" in t["description"])
    assert debit["type"] == "DEBIT"
    assert debit["amount"] == pytest.approx(-350.00)

    assert debug.get("txCount", 0) >= len(txs)


def test_parse_banco_do_brasil_bank_statement_rejects_non_bb() -> None:
    raw = "Extrato Banco X\nPeríodo: 01/01/2026 a 31/01/2026\n02 TESTE 10,00"
    result, warnings, _debug = parse_banco_do_brasil_bank_statement(raw)

    assert result["reason"] == "UNSUPPORTED_LAYOUT"
    assert warnings and warnings[0] == "not_banco_do_brasil"


def test_parse_banco_do_brasil_bank_statement_ignores_footer_noise_lines() -> None:
    raw = """
BANCO DO BRASIL
Extrato de Conta Corrente
Período: 01/01/2026 a 31/01/2026
Dia Lote Documento Histórico Valor
31 0000 12345 PIX RECEBIDO FULANO 600,00 C
- Limite Classic Taxa Limite Especial da Conta ao Mês 7,98%
Total Aplicações Financeiras * Saldos por dia Base Sujeitos a confirmação no momento da contratação
""".strip()

    result, _warnings, _debug = parse_banco_do_brasil_bank_statement(raw)

    non_balance = [t for t in result["transactions"] if t["type"] != "BALANCE"]
    assert len(non_balance) == 1
    assert "PIX RECEBIDO" in non_balance[0]["description"]
    assert non_balance[0]["amount"] == pytest.approx(600.00)


def test_parse_banco_do_brasil_bank_statement_handles_plus_minus_and_stops_before_info_sections() -> None:
    raw = """
BANCO DO BRASIL
Extrato de Conta Corrente
Período: 01/01/2026 a 31/01/2026
Dia Lote Documento Histórico Valor
14/01/2026 99020 730347300089299 Pgto cartão crédito 4.039,88 (-)
14/01/2026 13105 11401 Pix - Enviado 150,00 (-)
14/01/2026 9903 BB Rende Fácil 4.189,88 (+)
31/01/2026 Saldo do dia 345,87 (-)
Informações Adicionais
Limite Classic 600,00
Informações Complementares - CET (*) Valor Total Devido 651,63
""".strip()

    result, warnings, _debug = parse_banco_do_brasil_bank_statement(raw)

    txs = result["transactions"]
    non_balance = [t for t in txs if t["type"] != "BALANCE"]

    assert len(non_balance) == 3
    assert all("Informações" not in t["description"] for t in non_balance)

    assert non_balance[0]["type"] == "DEBIT"
    assert non_balance[0]["amount"] == pytest.approx(-4039.88)

    assert non_balance[1]["type"] == "DEBIT"
    assert non_balance[1]["amount"] == pytest.approx(-150.00)

    assert non_balance[2]["type"] == "CREDIT"
    assert non_balance[2]["amount"] == pytest.approx(4189.88)

    assert result["closingBalance"] == pytest.approx(-345.87)
    assert "missing_amount_on_tx_line" not in warnings


def test_parse_banco_do_brasil_bank_statement_handles_valor_and_saldo_columns() -> None:
    raw = """
BANCO DO BRASIL
Extrato de Conta Corrente
Período: 01/01/2026 a 31/01/2026
Movimentação C/C
Data Descrição Valor Saldo
31/12/2025 SALDO ANTERIOR R$ 0,00 R$ 0,00
02/01/2026 Juros Saldo Devedor Conta Cobrança de I.O.F. R$ 6,21 R$ 0,00
02/01/2026 IOF Saldo Devedor Conta BB Rende Fácil R$ 2,75 R$ 0,00
02/01/2026 Rende Facil R$ 8,96 R$ 0,00
31/01/2026 S A L D O R$ 345,87 R$ 0,00
""".strip()

    result, warnings, _debug = parse_banco_do_brasil_bank_statement(raw)

    assert "not_banco_do_brasil" not in warnings
    assert result["openingBalance"] == pytest.approx(0.00)
    assert result["closingBalance"] == pytest.approx(345.87)

    non_balance = [t for t in result["transactions"] if t["type"] != "BALANCE"]
    assert len(non_balance) == 3

    assert non_balance[0]["amount"] == pytest.approx(-6.21)
    assert non_balance[1]["amount"] == pytest.approx(-2.75)
    assert non_balance[2]["type"] == "CREDIT"
    assert non_balance[2]["amount"] == pytest.approx(8.96)
