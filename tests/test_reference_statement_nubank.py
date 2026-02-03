from __future__ import annotations

from pathlib import Path

from parsers.nubank_bank_statement import parse_nubank_bank_statement


def test_reference_statement_nubank() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "nubank_bank_statement_reference.txt"
    assert fixture_path.exists(), (
        "Fixture não encontrado em tests/fixtures/nubank_bank_statement_reference.txt. "
        "Gere-o chamando o endpoint /parse/nubank-bank-statement (que salva o raw_text automaticamente)."
    )

    text = fixture_path.read_text(encoding="utf-8", errors="replace")
    result, warnings, debug = parse_nubank_bank_statement(text)

    assert result["bank"] == "NUBANK"
    assert result["statementDate"] == "2025-12-31"
    assert result["openingBalance"] == 9.29
    assert result["closingBalance"] == 1133.05

    txs = result.get("transactions", [])
    assert len(txs) >= 6

    for tx in txs:
        assert "transactionDate" in tx
        assert "description" in tx
        assert "amount" in tx
        assert "type" in tx

        # Contrato: amount deve ser coerente com o type
        amount = float(tx.get("amount") or 0)
        if tx.get("type") == "DEBIT":
            assert amount <= 0
        if tx.get("type") == "CREDIT":
            assert amount >= 0

        # Descrição não deve explodir com dados de conta
        desc = (tx.get("description") or "")
        assert len(desc) <= 120
        assert "Agência" not in desc
        assert "Conta" not in desc

    # Heurística: pagamentos/saídas devem ser negativos
    debits = [t for t in txs if t.get("type") == "DEBIT"]
    credits = [t for t in txs if t.get("type") == "CREDIT"]
    assert debits
    assert credits

    assert any("Pagamento de fatura" in (t.get("description") or "") for t in txs)
    assert any("Compra no débito" in (t.get("description") or "") for t in txs)

    # Não é obrigatório ficar vazio, mas não deve marcar como unsupported
    assert result.get("reason") != "UNSUPPORTED_LAYOUT"

    # Warnings/debug são auxiliares
    assert isinstance(warnings, list)
    assert isinstance(debug, dict)
