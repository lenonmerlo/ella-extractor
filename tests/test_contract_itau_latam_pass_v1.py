from __future__ import annotations

from pathlib import Path

from parsers.itau_latam_pass import parse_itau_latam_pass


def test_itau_latam_pass_contract_v1_additive_fields_present_and_consistent() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "itau_latam_pass_reference.txt"
    assert fixture_path.exists(), "Fixture itau_latam_pass_reference.txt não encontrado"

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    payload, _warnings, _debug = parse_itau_latam_pass(text)

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
