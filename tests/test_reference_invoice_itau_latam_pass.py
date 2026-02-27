from __future__ import annotations

from pathlib import Path

from parsers.itau_latam_pass import parse_itau_latam_pass


def test_reference_invoice_itau_latam_pass() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "itau_latam_pass_reference.txt"
    assert fixture_path.exists(), (
        "Fixture não encontrado em tests/fixtures/itau_latam_pass_reference.txt. "
        "Gere-o chamando o endpoint /parse/itau-latam-pass (que salva o raw_text automaticamente)."
    )

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, _warnings, _debug = parse_itau_latam_pass(text)

    assert result["bank"] == "itau_latam_pass"
    assert result["dueDate"] == "2026-02-25"
    assert result["total"] == 1833.31

    txs = result["transactions"]
    assert isinstance(txs, list)
    assert len(txs) > 0

    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx
