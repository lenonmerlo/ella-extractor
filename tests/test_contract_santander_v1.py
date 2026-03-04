from __future__ import annotations

from parsers.santander import parse_santander


def test_santander_contract_v1_additive_fields_present_and_consistent() -> None:
    text = """
    Santander
    Total a Pagar R$ 1.381,94
    Vencimento 25/02/2026

    MARIANA O DE CASTRO - 5228 XXXX XXXX 6605
    Pagamento e Demais Créditos
    21/01 PAGAMENTO DE FATURA -2.428,83
    Despesas
    18/02 ANUIDADE DIFERENCIADA 166,66

    MARISA A O CASTRO - 5228 XXXX XXXX 5916
    Parcelamentos
    27/12 PAGUE MENOS 05 02/02 165,08
    09/01 DUTY PAID GUARULHOS I 02/03 189,33
    Despesas
    22/01 PAPEL JORNAL PAPELARIA 79,80
    27/01 MERCANTIL DO CONSUMIDO 277,07
    29/01 AVATIM 142,00
    31/01 NETFLIX ENTRETENIMENTO 59,90
    01/02 DROGASIL 3692 217,17
    01/02 MERCANTILCENTER 76,98
    16/02 IFD*IFOOD CLUB 7,95
    """.strip()

    payload = parse_santander(text)

    assert payload.get("parserContractVersion") == "1.0.0"

    summary = payload.get("summary")
    assert isinstance(summary, dict)
    assert "invoiceTotal" in summary
    assert "signedTransactionsTotal" in summary
    assert "transactionCount" in summary

    txs = payload.get("transactions") or []
    signed_sum = round(sum(float(t.get("amount") or 0) for t in txs), 2)
    assert summary["signedTransactionsTotal"] == signed_sum
    assert summary["transactionCount"] == len(txs)

    reconciliation = payload.get("reconciliation")
    assert isinstance(reconciliation, dict)
    assert reconciliation.get("threshold") == 0.01

    total = payload.get("total")
    if total is not None:
        expected_diff = round(float(total) - signed_sum, 2)
        assert reconciliation.get("difference") == expected_diff
        assert reconciliation.get("isBalanced") == (abs(expected_diff) <= 0.01)
