from __future__ import annotations

from parsers.c6_invoice import parse_c6_invoice


def test_c6_total_prefers_invoice_total_over_installment_simulation() -> None:
    text = """
    C6 BANK
    Olá, Lenon! Sua fatura com vencimento em Dezembro chegou no valor de R$ 5.098,40.
    Vencimento: 20/12/2025
    Valor da fatura: R$ 5.098,40
    Total a pagar R$ 5.098,40

    Parcelamento Total a pagar CET
    R$ 7.012,90 Entrada + 9x de R$ 701,29 152,52% a.a.
    R$ 7.489,92 Entrada + 11x de R$ 624,16 152,64% a.a.

    Transações do cartão principal
    C6 Carbon Virtual Final 5867 - TITULAR
    27 out AIRBNB * HMF99EFWK9 - Parcela 2/3 369,48
    21 nov Inclusao de Pagamento 5.698,02
    09 dez Estorno Tarifa - Estorno 98,00
    09 dez Anuidade Diferenciada - Parcela 11/12 98,00
    """.strip()

    payload = parse_c6_invoice(text)

    assert payload["bank"] == "C6"
    assert payload["dueDate"] == "2025-12-20"
    assert payload["total"] == 5098.40

    txs = payload.get("transactions") or []
    descriptions = [str(t.get("description") or "") for t in txs]
    assert all("inclusao de pagamento" not in d.lower() for d in descriptions)
