from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from parsers.itau_personnalite import normalize_text, parse_itau_personnalite


_EXPECTED_REFERENCE_TRANSACTIONS_COUNT = 38
_EXPECTED_CARD_FINALS = {
    "8578",
    "2673",
    "0375",
    "5848",
    "5663",
    "6343",
    "0527",
    "4973",
}


def _load_reference_text() -> str:
    # 38 is a property of *this* reference file only.
    # Other invoices will legitimately have different transaction counts.
    env_path = os.getenv("ITAU_PERSONNALITE_REFERENCE_TEXT_PATH")
    if env_path:
        path = Path(env_path)
    else:
        path = Path(__file__).resolve().parent / "fixtures" / "itau_personnalite_reference.txt"

    if not path.exists():
        pytest.skip(
            "Reference Itaú Personnalité fixture not found. "
            "Create extractor/tests/fixtures/itau_personnalite_reference.txt "
            "or set ITAU_PERSONNALITE_REFERENCE_TEXT_PATH to an absolute path."
        )

    return path.read_text(encoding="utf-8", errors="replace")


def _first_parceladas_index(text: str) -> int:
    # Use a tolerant match: with/without accents, with/without extra whitespace.
    m = re.search(r"(?is)compras\s*parceladas", text)
    if m:
        return m.start()

    # Fall back to normalized text, then find a nearby index in original text by searching a plain token.
    normalized = normalize_text(text)
    m2 = re.search(r"(?is)compras\s*parceladas", normalized)
    if not m2:
        return -1

    return text.lower().find("compras parceladas")


def _mutate_holder_names(text: str) -> str:
    # Requirement: holder name must not affect extraction.
    # We mutate lines that look like card holder headers (contain final#### but do NOT contain a date).
    out_lines: list[str] = []
    for line in text.splitlines():
        has_final = re.search(r"(?i)\bfinal\s*\d{4}\b", line) is not None
        has_date = re.search(r"\b\d{2}/\d{2}\b", line) is not None

        if has_final and not has_date:
            # Replace everything before "final ####" while preserving the final digits.
            line = re.sub(
                r"(?is)^.*?(?=(?:\(|\b)\s*final\s*\d{4}\s*(?:\)|\b))",
                "TITULAR ALTERADO ",
                line,
            )

        out_lines.append(line)

    return "\n".join(out_lines)


@pytest.mark.reference_invoice
def test_reference_invoice_transactions_count_and_fields() -> None:
    text = _load_reference_text()

    result, _warnings, debug = parse_itau_personnalite(text)

    # This count is specific to the reference file used by this test.
    assert debug.get("transactionsCount") == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT
    assert len(result.get("transactions", [])) == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT

    txs = result["transactions"]
    for tx in txs:
        assert "date" in tx and isinstance(tx["date"], str) and tx["date"].strip()
        assert "description" in tx and isinstance(tx["description"], str) and tx["description"].strip()
        assert "amount" in tx and isinstance(tx["amount"], (int, float))
        assert "cardFinal" in tx and isinstance(tx["cardFinal"], str) and re.fullmatch(r"\d{4}", tx["cardFinal"]) is not None

        # Guardrail: nothing related to parceladas should ever leak into parsed transactions.
        desc_l = tx["description"].lower()
        assert "compras parceladas" not in desc_l
        assert "proximas faturas" not in desc_l
        assert "próximas faturas" not in desc_l

    observed_finals = {tx["cardFinal"] for tx in txs}
    assert _EXPECTED_CARD_FINALS.issubset(observed_finals)


@pytest.mark.reference_invoice
def test_reference_invoice_no_transactions_from_after_parceladas_section() -> None:
    text = _load_reference_text()

    idx = _first_parceladas_index(text)
    assert idx != -1, "Reference text must contain the 'Compras parceladas' marker"

    result_full, _warnings_full, debug_full = parse_itau_personnalite(text)
    result_truncated, _warnings_trunc, debug_truncated = parse_itau_personnalite(text[:idx])

    assert debug_full.get("transactionsCount") == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT
    assert debug_truncated.get("transactionsCount") == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT

    # If anything was being incorrectly parsed from below "Compras parceladas",
    # truncating the text at the marker would change the extracted transactions.
    def key(tx: dict) -> tuple:
        return (
            tx.get("date"),
            round(float(tx.get("amount")), 2),
            normalize_text(str(tx.get("description") or "")),
            tx.get("cardFinal"),
        )

    assert {key(tx) for tx in result_full["transactions"]} == {key(tx) for tx in result_truncated["transactions"]}


@pytest.mark.reference_invoice
def test_reference_invoice_holder_name_changes_do_not_affect_parsing() -> None:
    text = _load_reference_text()
    mutated = _mutate_holder_names(text)

    result_a, _warnings_a, debug_a = parse_itau_personnalite(text)
    result_b, _warnings_b, debug_b = parse_itau_personnalite(mutated)

    assert debug_a.get("transactionsCount") == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT
    assert debug_b.get("transactionsCount") == _EXPECTED_REFERENCE_TRANSACTIONS_COUNT

    def key(tx: dict) -> tuple:
        return (
            tx.get("date"),
            round(float(tx.get("amount")), 2),
            normalize_text(str(tx.get("description") or "")),
            tx.get("cardFinal"),
        )

    assert {key(tx) for tx in result_a["transactions"]} == {key(tx) for tx in result_b["transactions"]}
