from __future__ import annotations

from pathlib import Path

from parsers.santander import extract_due_date, extract_total, extract_transactions, parse_santander


def _sample_text() -> str:
    return """
    Santander
    Total a Pagar R$ 1.381,94
    Vencimento 25/02/2026

    Detalhamento da Fatura
    MARIANA O DE CASTRO - 5228 XXXX XXXX 6605

    Pagamento e Demais Créditos
    Compra Data Descrição Parcela R$ US$
    21/01 PAGAMENTO DE FATURA -2.428,83

    Despesas
    Compra Data Descrição Parcela R$ US$
    1/02 ANUIDADE DIFERENCIADA 166,66 0,00

    MARISA A O CASTRO - 5228 XXXX XXXX 5916

    Parcelamentos
    27/12 PAGUE MENOS 05 02/02 165,08
    09/01 DUTY PAID GUARULHOS I 02/03 189,33

    Despesas
    22/01 PAPEL JORNAL PAPELARIA 79,80
    27/01 MERCANTIL DO CONSUMIDO 277,07
    29/01 ATIV 142,00
    31/01 NETFLIX ENTRETENIMENTO 59,90
    01/02 DROGASIL 3692 217,17
    01/02 MERCANTILCENTER 76,98
    16/02 IFD*FOOD CLUB 7,95

    Resumo da Fatura
    (-) Saldo Desta Fatura 1.381,94
    """.strip()


def test_extract_due_date_and_total() -> None:
    text = _sample_text()

    due = extract_due_date(text)
    assert due is not None
    assert due.isoformat() == "2026-02-25"

    total = extract_total(text)
    assert total == 1381.94


def test_extract_transactions_skips_payment_of_previous_invoice_and_keeps_installments() -> None:
    txs = extract_transactions(_sample_text())

    assert len(txs) == 10
    assert not any("PAGAMENTO DE FATURA" in (tx.get("description") or "") for tx in txs)

    pague_menos = [tx for tx in txs if (tx.get("description") or "").startswith("PAGUE MENOS")]
    assert len(pague_menos) == 1
    assert pague_menos[0].get("installment") == {"current": 2, "total": 2}

    assert any(tx.get("cardFinal") == "6605" for tx in txs)
    assert any(tx.get("cardFinal") == "5916" for tx in txs)


def test_parse_santander_contract_v1_reconciliation_balances_sample() -> None:
    payload = parse_santander(_sample_text())

    assert payload["parserContractVersion"] == "1.0.0"
    assert payload["bank"] == "SANTANDER"
    assert payload["dueDate"] == "2026-02-25"
    assert payload["total"] == 1381.94

    summary = payload["summary"]
    assert summary["transactionCount"] == 10
    assert summary["signedTransactionsTotal"] == 1381.94

    reconciliation = payload["reconciliation"]
    assert reconciliation["difference"] == 0.0
    assert reconciliation["isBalanced"] is True


def test_extract_transactions_handles_ocr_noise_before_date() -> None:
    text = _sample_text().replace(
        "27/12 PAGUE MENOS 05 02/02 165,08",
        ")) ) 27/12 PAGUE MENOS 05 02/02 165,08",
    ).replace(
        "31/01 NETFLIX ENTRETENIMENTO 59,90",
        "@ 31/01 NETFLIX ENTRETENIMENTO 59,90",
    )

    txs = extract_transactions(text)

    assert len(txs) == 10
    assert any((tx.get("description") or "").startswith("PAGUE MENOS") for tx in txs)
    assert any((tx.get("description") or "").startswith("NETFLIX ENTRETENIMENTO") for tx in txs)


def test_extract_due_date_accepts_two_digit_year() -> None:
    text = _sample_text().replace("Vencimento 25/02/2026", "Vencimento 25/02/26")

    due = extract_due_date(text)

    assert due is not None
    assert due.isoformat() == "2026-02-25"


def test_extract_transactions_ignores_vencimento_line_with_amount() -> None:
    text = """
    Santander
    Vencimento 25/02/2026 R$ 1.733,60
    Total a pagar R$ 1.733,60

    MARIANA O DE CASTRO - 5228 XXXX XXXX 6605
    Despesas
    18/02 ANUIDADE DIFERENCIADA 166,66
    """.strip()

    txs = extract_transactions(text)

    assert len(txs) == 1
    assert txs[0]["date"] == "2026-02-18"
    assert txs[0]["description"] == "ANUIDADE DIFERENCIADA"
    assert txs[0]["amount"] == 166.66


def test_parse_santander_large_reference_layout_extracts_due_date_and_avoids_merged_rows() -> None:
    text = Path("tests/fixtures/santander_reference.txt").read_text(encoding="utf-8")

    payload = parse_santander(text)

    assert payload["dueDate"] == "2025-12-20"
    assert payload["total"] == 44815.95

    txs = payload["transactions"]
    assert len(txs) >= 50

    merged_markers = (
        " 2 20/06 ",
        " 2 29/11 ",
        " 2 30/11 ",
        " 08/12 AIRBNB",
    )
    assert not any(any(marker in (tx.get("description") or "") for marker in merged_markers) for tx in txs)

    by_desc = {tx.get("description"): tx for tx in txs}
    assert by_desc["SEAWORLD/BUSCH GARDENS"]["amount"] == 786.28
    assert by_desc["EURO DISNEY 1.208,00 EURO"]["amount"] == 7951.56
