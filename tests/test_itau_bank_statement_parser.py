from __future__ import annotations

from datetime import date

from parsers.itau_bank_statement import looks_like_itau_bank_statement, parse_itau_bank_statement


def test_itau_bank_statement_detect_and_parse_minimal_sample() -> None:
    text = """
extrato conta / lançamentos
período de visualização: 04/10/2025 até 03/12/2025 emitido em: 03/12/2025 12:47:47

data lançamentos valor (R$) saldo (R$)
03/12/2025 SALDO DO DIA 18.866,23
03/12/2025 PIX TRANSF Raimund03/12 -25,00
02/12/2025 PAY PAGUE 02/12 -31,15
25/11/2025 PIX TRANSF SOLANGE25/11 855,00
25/11/2025 SALDO DO DIA 25.842,91
Aviso!
Os saldos acima são baseados nas informações disponíveis até esse instante
""".strip()

    assert looks_like_itau_bank_statement(text) is True

    result, warnings, debug = parse_itau_bank_statement(text)

    assert result["bank"] == "ITAU"
    assert result["statementDate"] == date(2025, 12, 3).isoformat()

    assert result["openingBalance"] > 0
    assert result["closingBalance"] > 0

    txs = result.get("transactions")
    assert isinstance(txs, list)
    assert len(txs) >= 5

    # BALANCE rows exist
    assert any(t.get("type") == "BALANCE" for t in txs)

    # Glued dd/mm fixed
    pix = next(t for t in txs if (t.get("description") or "").startswith("PIX TRANSF"))
    assert "Raimund 03/12" in pix.get("description", "")

    # Warnings/debug are allowed but should exist as dicts
    assert isinstance(warnings, list)
    assert isinstance(debug, dict)
