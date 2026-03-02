from __future__ import annotations

from pathlib import Path

from parsers.bradesco_fatura_mensal_v1 import parse_bradesco_fatura_mensal_v1


def test_reference_invoice_bradesco_fatura_mensal_v1() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "bradesco_fatura_mensal_v1_reference.txt"
    assert fixture_path.exists(), (
        "Fixture não encontrado em tests/fixtures/bradesco_fatura_mensal_v1_reference.txt. "
        "Gere-o chamando o endpoint /parse/bradesco-fatura-mensal-v1 (que salva o raw_text automaticamente)."
    )

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, _warnings, _debug = parse_bradesco_fatura_mensal_v1(text)

    assert result["bank"] == "bradesco_fatura_mensal_v1"
    assert result["dueDate"] == "2026-02-25"
    assert result["total"] == 15681.84

    txs = result["transactions"]
    assert isinstance(txs, list)
    assert len(txs) > 0

    for tx in txs:
        assert "date" in tx
        assert "description" in tx
        assert "amount" in tx

    # Ensure fee lines without leading date are captured.
    def has_tx(substr: str, amount: float) -> bool:
        s = substr.lower()
        for tx in txs:
            desc = str(tx.get("description") or "").lower()
            if s in desc and float(tx.get("amount")) == amount:
                return True
        return False

    assert has_tx("encargos sobre", 10.09)
    assert has_tx("iof diário sobre", 1.19) or has_tx("iof diario sobre", 1.19)
    assert has_tx("iof adicional sobre", 1.12)

    # Must not include demonstrative payment / legal note lines as transactions.
    assert not has_tx("pagto. por deb em c/c", 16044.43)
    assert not has_tx("de acordo com a legislação vigente", 0.38)

    # Ensure real transactions with glued table text don't get corrupted.
    assert has_tx("decorart comercio", 580.00)
    assert has_tx("bradesco auto", 44.30)

    # Ensure important launches from the user's sample are captured.
    assert has_tx("mary john fortaleza", 80.00)
    assert has_tx("one park ceara fortaleza", 15.00)
    assert has_tx("farmacia central comer", 76.25)
    assert has_tx("natural vida fortaleza", 30.00)
    assert has_tx("pizzaria cogumelos de guaramiran", 70.40)
    assert has_tx("mercadinho sao luiz fortaleza", 130.73)
    assert has_tx("padaria ideal abolica", 9.93)
    assert has_tx("pronace fortaleza", 32.75)
    assert has_tx("supermercado cometa fortaleza", 46.86)
    assert has_tx("arpao fortaleza", 120.34)
    assert has_tx("havaianas fortaleza", 7.00)
    assert has_tx("tio armenio fortaleza", 86.90)
    assert has_tx("des comercio varejist", 274.80)
    assert has_tx("seguro superprotegido", 9.99)
    assert has_tx("anuidade diferenciada", 160.00)
