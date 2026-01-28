from __future__ import annotations

from pathlib import Path

from parsers.itau_personnalite import parse_itau_personnalite


def test_reference_invoice_itau_personnalite() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "itau_personnalite_reference.txt"
    assert fixture_path.exists(), (
        "Fixture não encontrado em tests/fixtures/itau_personnalite_reference.txt. "
        "Gere-o chamando o endpoint /parse/itau-personnalite (que salva o raw_text automaticamente)."
    )

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, _warnings, _debug = parse_itau_personnalite(text)

    assert result["bank"] == "itau_personnalite"
    assert result["dueDate"] == "2025-12-01"
    assert result["total"] == 3760.96

    # 38 é esperado apenas para esta fatura de referência (este fixture específico).
    # Outras faturas podem ter mais ou menos lançamentos.
    assert len(result["transactions"]) == 38

    for tx in result["transactions"]:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx

    observed_finals = {tx.get("cardFinal") for tx in result["transactions"] if tx.get("cardFinal")}
    assert {
        "8578",
        "2673",
        "0375",
        "5848",
        "5663",
        "6343",
        "0527",
        "4973",
    }.issubset(observed_finals)
