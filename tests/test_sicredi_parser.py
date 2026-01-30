from __future__ import annotations

from parsers.sicredi import extract_due_date, extract_total, extract_transactions, parse_sicredi


def test_extract_due_date_ddmmyyyy() -> None:
    text = "Resumo da fatura\nVencimento: 25/11/2025\n"
    d = extract_due_date(text)
    assert d is not None
    assert d.isoformat() == "2025-11-25"


def test_extract_due_date_dd_mon_infers_year_from_document() -> None:
    # When the due date is shown as dd/mon, infer the year from any dd/MM/yyyy present.
    text = "Vencimento 25/nov\nEmitido em 01/11/2025\n"
    d = extract_due_date(text)
    assert d is not None
    assert d.isoformat() == "2025-11-25"


def test_extract_total_parses_total_fatura_de_mes() -> None:
    text = "Total fatura de novembro R$ 12.068,55"
    assert extract_total(text) == 12068.55


def test_extract_total_parses_pagamento_total_rs() -> None:
    text = "Pagamento total (R$) R$ 1.234,56"
    assert extract_total(text) == 1234.56


def test_extract_transactions_preserves_legitimate_identical_lines() -> None:
    # Two identical purchases must remain as two distinct transactions.
    text = """
    Resumo da fatura
    Vencimento: 25/11/2025
    Transações
    Data e hora Estabelecimento Valor em reais
    11/nov 10:10 UBER*TRIP R$ 10,00
    11/nov 10:10 UBER*TRIP R$ 10,00
    """.strip()

    txs = extract_transactions(text)
    assert len(txs) == 2
    assert txs[0]["date"] == "2025-11-11"
    assert txs[1]["date"] == "2025-11-11"
    assert txs[0]["amount"] == 10.00
    assert txs[1]["amount"] == 10.00


def test_extract_transactions_sets_card_final_from_context_and_inline_override() -> None:
    text = """
    Vencimento: 25/11/2025
    Transações
    Data e hora Estabelecimento Valor em reais
    final 2127
    11/nov 06:13 MERCADO X R$ 4,90
    12/nov 07:00 PADARIA Y final 2911 R$ 7,00
    """.strip()

    txs = extract_transactions(text)
    assert len(txs) == 2

    assert txs[0]["cardFinal"] == "2127"
    assert txs[1]["cardFinal"] == "2911"


def test_extract_transactions_parses_installment_token() -> None:
    text = """
    Vencimento: 25/11/2025
    Transações
    Data e hora Estabelecimento Valor em reais
    11/nov 06:13 LOJA PARCELADA 01/10 R$ 198,00
    """.strip()

    txs = extract_transactions(text)
    assert len(txs) == 1
    assert txs[0]["installment"] == {"current": 1, "total": 10}
    assert txs[0]["amount"] == 198.00


def test_extract_transactions_keeps_negative_amount_for_credits() -> None:
    # Credits/payments are represented as negative amounts in the extractor.
    text = """
    Vencimento: 25/11/2025
    Transações
    Data e hora Estabelecimento Valor em reais
    12/nov 08:00 ESTORNO XYZ -R$ 50,00
    """.strip()

    txs = extract_transactions(text)
    assert len(txs) == 1
    assert txs[0]["amount"] == -50.00


def test_parse_sicredi_returns_structured_payload() -> None:
    text = """
    Resumo da fatura
    Vencimento: 25/11/2025
    Total fatura de novembro R$ 12.068,55
    Transações
    Data e hora Estabelecimento Valor em reais
    final 2127
    11/nov 06:13 MERCADO X R$ 4,90
    """.strip()

    payload = parse_sicredi(text)
    assert payload["bank"] == "SICREDI"
    assert payload["dueDate"] == "2025-11-25"
    assert payload["total"] == 12068.55
    assert isinstance(payload.get("transactions"), list)
    assert len(payload["transactions"]) == 1
