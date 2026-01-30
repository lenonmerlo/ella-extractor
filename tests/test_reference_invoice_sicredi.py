from __future__ import annotations

from pathlib import Path

from parsers.sicredi import parse_sicredi


def test_reference_invoice_sicredi() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "sicredi_reference.txt"
    assert fixture_path.exists(), (
        "Fixture não encontrado em tests/fixtures/sicredi_reference.txt. "
        "Gere-o chamando o endpoint /parse/sicredi (que salva o raw_text automaticamente)."
    )

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result = parse_sicredi(text)

    assert result["bank"] == "SICREDI"
    assert result["dueDate"] == "2025-11-25"
    assert result["total"] == 12068.55

    txs = result.get("transactions", [])
    assert len(txs) == 101

    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx

    observed_finals = {tx.get("cardFinal") for tx in txs if tx.get("cardFinal")}
    assert {"2127", "2911"}.issubset(observed_finals)

    # This fixture includes credits/estornos; ensure they remain present.
    negatives = [tx for tx in txs if float(tx.get("amount") or 0) < 0]
    assert len(negatives) == 2

    # Contract: signed sum of txs should match the header total for this fixture.
    signed_sum = round(sum(float(tx.get("amount") or 0) for tx in txs), 2)
    assert signed_sum == result["total"]
