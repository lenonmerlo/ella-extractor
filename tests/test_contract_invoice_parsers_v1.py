from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from parsers.bradesco_fatura_mensal_v1 import parse_bradesco_fatura_mensal_v1
from parsers.banco_do_brasil import parse_banco_do_brasil
from parsers.c6_invoice import parse_c6_invoice
from parsers.itau_latam_pass import parse_itau_latam_pass
from parsers.itau_personnalite import parse_itau_personnalite
from parsers.santander import parse_santander
from parsers.sicredi import parse_sicredi


def _fixtures_dir() -> Path:
    return Path(__file__).resolve().parent / "fixtures"


def _parse_result(payload_or_tuple: Any) -> dict[str, Any]:
    if isinstance(payload_or_tuple, tuple):
        return payload_or_tuple[0]
    return payload_or_tuple


def _load_fixture(name: str) -> str:
    path = _fixtures_dir() / name
    assert path.exists(), f"Fixture {name} não encontrado"
    return path.read_text(encoding="utf-8", errors="replace")


def _sample_santander() -> str:
    return """
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


def _sample_banco_do_brasil() -> str:
    return """
    BANCO DO BRASIL
    OUROCARD VISA INFINITE Final 9194
    Resumo da fatura
    Total da Fatura R$ 14.118,91
    Vencimento 25/09/2025

    Data    Descrição País Valor
    20/08 PGTO. COBRANCA 2958 BR R$ -84,00
    21/08 911 MUSEUM WEB 646-757-5567 NY R$ 409,79
    27/08 TM *TICKETMASTER 8006538000 CA R$ 2.533,65
    22/08 IOF - COMPRA NO EXTERIOR R$ 4,50
    """.strip()


def _sample_c6_invoice() -> str:
    return """
    C6 BANK
    Olá! Sua fatura com vencimento em Dezembro chegou no valor de R$ 5.098,40
    Vencimento: 20/12/2025
    Transações do cartão principal
    C6 Carbon Virtual Final 5867 - TITULAR
    27 out AIRBNB * HMF99EFWK9 - Parcela 2/3 369,48
    14 nov BAR PIMENTA CARIOCA 92,40
    09 dez Estorno Tarifa - Estorno 98,00
    C6 Carbon Virtual Final 1234 - TITULAR
    21 nov Inclusao de Pagamento 5.698,02
    """.strip()


def _itau_personnalite_fixture_or_skip() -> str:
    text = _load_fixture("itau_personnalite_reference.txt")
    low = text.lower()
    if "itau" not in low and "personnalite" not in low and "personalite" not in low:
        pytest.skip("Fixture atual de itau_personnalite não parece ser Itaú Personnalité (sobrescrito localmente).")
    return text


CASES: list[tuple[str, Callable[[str], Any], Callable[[], str]]] = [
    ("banco_do_brasil", parse_banco_do_brasil, _sample_banco_do_brasil),
    ("c6_invoice", parse_c6_invoice, _sample_c6_invoice),
    ("sicredi", parse_sicredi, lambda: _load_fixture("sicredi_reference.txt")),
    (
        "bradesco_fatura_mensal_v1",
        parse_bradesco_fatura_mensal_v1,
        lambda: _load_fixture("bradesco_fatura_mensal_v1_reference.txt"),
    ),
    ("itau_personnalite", parse_itau_personnalite, _itau_personnalite_fixture_or_skip),
    ("itau_latam_pass", parse_itau_latam_pass, lambda: _load_fixture("itau_latam_pass_reference.txt")),
    ("santander", parse_santander, _sample_santander),
]


@pytest.mark.parametrize("name,parser,source", CASES)
def test_invoice_parsers_contract_v1_aggregate(
    name: str,
    parser: Callable[[str], Any],
    source: Callable[[], str],
) -> None:
    payload = _parse_result(parser(source()))

    assert payload.get("parserContractVersion") == "1.0.0", f"{name}: version"

    summary = payload.get("summary")
    assert isinstance(summary, dict), f"{name}: summary"
    assert "invoiceTotal" in summary, f"{name}: invoiceTotal"
    assert "signedTransactionsTotal" in summary, f"{name}: signedTransactionsTotal"
    assert "transactionCount" in summary, f"{name}: transactionCount"

    txs = payload.get("transactions") or []
    signed_sum = round(sum(float(t.get("amount") or 0) for t in txs), 2)
    assert summary["signedTransactionsTotal"] == signed_sum, f"{name}: signed sum"
    assert summary["transactionCount"] == len(txs), f"{name}: tx count"

    reconciliation = payload.get("reconciliation")
    assert isinstance(reconciliation, dict), f"{name}: reconciliation"
    assert reconciliation.get("threshold") == 0.01, f"{name}: threshold"

    total = payload.get("total")
    if total is not None:
        expected_diff = round(float(total) - signed_sum, 2)
        assert reconciliation.get("difference") == expected_diff, f"{name}: difference"
        assert reconciliation.get("isBalanced") == (abs(expected_diff) <= 0.01), f"{name}: isBalanced"
