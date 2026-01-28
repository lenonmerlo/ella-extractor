from __future__ import annotations

from parsers.itau_personnalite import (
    extract_total,
    extract_transactions,
    parse_itau_personnalite,
    slice_transactions_section,
)


def test_splits_two_transactions_in_same_line() -> None:
    # Real-world glued line example from pdfplumber extraction
    section_text = "19/05 COSSERVICOSMEDIC07/10 500,00 30/10 UBER*TRIP 19,54"

    txs, debug = extract_transactions(section_text, year=2025)

    assert debug["splitLinesCount"] == 1
    assert len(txs) == 2

    assert txs[0]["date"] == "2025-05-19"
    assert txs[0]["amount"] == 500.00
    assert "COSSERVICOSMEDIC" in txs[0]["description"].replace(" ", "")

    assert txs[1]["date"] == "2025-10-30"
    assert txs[1]["amount"] == 19.54
    assert "UBER" in txs[1]["description"].upper()


def test_does_not_split_on_installment_date_inside_description() -> None:
    # Real-world example where a dd/MM inside the merchant/description is an installment marker,
    # not a new transaction start.
    section_text = "11/06 LOUNGERIESA 06/06 55,96 30/10 UBER*TRIP 21,50"

    txs, debug = extract_transactions(section_text, year=2025)

    assert "droppedSegmentsCount" in debug
    assert "droppedSegmentsExamples" in debug

    # Should split into exactly 2 transactions (11/06 and 30/10).
    assert debug["splitLinesCount"] == 1
    assert len(txs) == 2

    assert txs[0]["date"] == "2025-06-11"
    assert txs[0]["amount"] == 55.96

    assert txs[1]["date"] == "2025-10-30"
    assert txs[1]["amount"] == 21.50

    # Ensure we didn't create a bogus transaction for the installment date.
    assert not any(tx["date"] == "2025-06-06" and tx["amount"] == 55.96 for tx in txs)

    # Ensure split segments don't contain the bogus standalone "06/06 55,96" segment.
    assert debug["splitExamples"], "Expected splitExamples to include this line"
    assert all(
        seg.strip() != "06/06 55,96"
        for example in debug["splitExamples"]
        for seg in example.get("segments", [])
    )


def test_extract_total_fallback_matches_glued_totaldestafatura() -> None:
    text = "Totaldestafatura 3.760,96\nR$ 3.760,96 01/12/2025"
    assert extract_total(text) == 3760.96


def test_captures_transaction_after_card_header_line() -> None:
    section_text = "ANAPAULASC(final8578) 30/10 UBER*TRIP 17,56"
    txs, _debug = extract_transactions(section_text, year=2025)

    assert len(txs) == 1
    assert txs[0]["date"] == "2025-10-30"
    assert txs[0]["amount"] == 17.56
    assert txs[0]["description"].upper() == "UBER*TRIP"


def test_truncates_contaminated_line_with_encargos_suffix() -> None:
    # Some PDFs glue the "Encargos/Juros" block at the end of a valid purchase line.
    # Without truncation, the last amount becomes 0,00 and the tx is corrupted.
    section_text = (
        "26/07 CONSUL *CONSU 317,05 Encargos cobrados nesta fatura Juros do rotativo 0,00"
    )
    txs, _debug = extract_transactions(section_text, year=2025)

    assert len(txs) == 1
    assert txs[0]["date"] == "2025-07-26"
    assert txs[0]["description"].upper() == "CONSUL *CONSU"
    assert txs[0]["amount"] == 317.05


def test_stops_parsing_when_encargos_block_header_is_reached() -> None:
    section_text = "\n".join(
        [
            "26/07 CONSUL *CONSU 317,05",
            "Encargos cobrados nesta fatura",
            "27/07 SHOULDNOTPARSE 10,00",
        ]
    )

    txs, _debug = extract_transactions(section_text, year=2025)

    assert len(txs) == 1
    assert txs[0]["date"] == "2025-07-26"
    assert txs[0]["amount"] == 317.05


def test_slice_transactions_section_ends_before_encargos_line_exclusive() -> None:
    full_text = "\n".join(
        [
            "Lanamentos:comprasesaques",
            "26/07 CONSUL *CONSU 317,05",
            "Encargoscobradosnestafatura",
            "Jurosdorotativo 10,50% 0,00",
        ]
    )

    section, debug = slice_transactions_section(full_text)

    assert debug.get("sectionFound") is True
    assert debug.get("endMarker")
    assert "encargos" in str(debug.get("endMarker")).lower()

    # End marker must be excluded from the section.
    assert "Encargoscobradosnestafatura" not in section

    txs, _tx_debug = extract_transactions(section, year=2025)
    assert any(tx["date"] == "2025-07-26" and tx["amount"] == 317.05 for tx in txs)


def test_parse_extracts_transactions_from_multiple_lancamentos_blocks_and_stops_at_parceladas() -> None:
    # The parser must:
    # - start at the first "Lançamentos: compras e saques"
    # - include transactions from multiple "Lançamentos" blocks that appear BEFORE the first
    #   "Compras parceladas" marker
    # - stop globally at the first "Compras parceladas" marker (nothing after it is parsed)
    text = "\n".join(
        [
            "Vencimento: 01/12/2025",
            "Totaldestafatura 3.760,96",
            "Lanamentos:comprasesaques",
            "03/02 GOLLINHASA*QLKLP10/10 119,72",
            "Lanamentos:comprasesaques",
            "Lanamentosnocarto(final8578)",
            "ANAPAULASC(final8578)",
            "26/07 CONSUL *CONSU04/07 317,05",
            "Compras parceladas - proximas faturas",
            "30/10 SHOULD_NOT_PARSE 10,00",
        ]
    )

    payload, warnings, _debug = parse_itau_personnalite(text)
    assert "total_not_found" not in warnings

    txs = payload.get("transactions", [])
    assert any(tx["date"] == "2025-02-03" and abs(tx["amount"] - 119.72) < 0.001 for tx in txs)

    consul = [tx for tx in txs if tx["date"] == "2025-07-26" and abs(tx["amount"] - 317.05) < 0.001]
    assert consul, "Expected CONSUL 317,05 transaction from the 2nd block"
    assert consul[0].get("cardFinal") == "8578"

    # Ensure transactions after "Compras parceladas" markers are never included.
    assert not any("SHOULD_NOT_PARSE" in (tx.get("description") or "") for tx in txs)


def test_parse_extracts_block_b_two_cards_and_dedupes_with_block_a() -> None:
    # Block A (generic launches) contains an UBER transaction.
    # Block B (per-card) repeats the same transaction, but must enrich with cardFinal and not duplicate.
    text = "\n".join(
        [
            "Vencimento: 01/12/2025",
            "Totaldestafatura 3.760,96",
            "Lanamentos:comprasesaques",
            "30/10 UBER*TRIP 64,21",
            "Lanamentos:comprasesaques",
            # Header formats should not depend on holder name.
            "ANA PAULA S C final2673",
            "DATA ESTABELECIMENTO VALOR EM R$",
            # Totals/header lines must be ignored as transactions, but can appear in the block.
            "Lanamentos no cartao(final2673) 119,72",
            # Real PDFs sometimes prefix the date with '@' and/or glue city after amount.
            "@03/02 GOL LINHAS A*QLKLP10/10 119,72 SAO PAULO",
            "30/10 UBER*TRIP 64,21",
            "ANAPAULA S C (final 0375)",
            "@01/02 ECOMMERCE MEIA SOL10/10 125,00",
            "01/11 AMAZON 99,00",
            "Compras parceladas - proximas faturas",
            "02/12 SHOULD_NOT_PARSE 10,00",
        ]
    )

    payload, warnings, debug = parse_itau_personnalite(text)
    assert "total_not_found" not in warnings
    assert debug.get("cardBlockTransactionsCount", 0) >= 3

    txs = payload.get("transactions", [])

    # From card final 2673
    assert any(
        tx.get("date") == "2025-02-03" and abs(tx.get("amount") - 119.72) < 0.001
        and tx.get("cardFinal") == "2673"
        for tx in txs
    )

    # From card final 0375 (leading zero preserved)
    assert any(
        tx.get("date") == "2025-02-01" and abs(tx.get("amount") - 125.00) < 0.001
        and tx.get("cardFinal") == "0375"
        for tx in txs
    )

    assert any(
        tx.get("date") == "2025-11-01"
        and abs(tx.get("amount") - 99.00) < 0.001
        and tx.get("cardFinal") == "0375"
        for tx in txs
    )

    # Dedup: UBER must appear only once, but with cardFinal enriched from block B.
    uber = [
        tx
        for tx in txs
        if tx.get("date") == "2025-10-30" and abs(tx.get("amount") - 64.21) < 0.001
    ]
    assert len(uber) == 1
    assert uber[0].get("cardFinal") == "2673"

    # Ensure the card total/header line did not turn into a transaction.
    assert not any(
        (tx.get("description") or "").lower().startswith("lanamentos no cartao")
        for tx in txs
    )

    # Ensure parceladas area never leaks.
    assert not any("SHOULD_NOT_PARSE" in (tx.get("description") or "") for tx in txs)


def test_extract_transactions_parses_gol_line_even_if_amount_is_glued() -> None:
    # Some PDFs glue the amount to the description without whitespace.
    section_text = "ANA PAULA S C (final 2673)\n@03/02 GOL LINHAS A*QLKLP10/10119,72"
    txs, _debug = extract_transactions(section_text, year=2025)

    assert any(
        tx.get("date") == "2025-02-03"
        and abs(tx.get("amount") - 119.72) < 0.001
        and tx.get("cardFinal") == "2673"
        for tx in txs
    )


def test_extract_transactions_handles_limite_tail_contamination() -> None:
    # Real-world issue: the transaction line gets glued with the "Limites de crédito" column,
    # causing the last money token to be the credit limit (e.g. 39.360,00) instead of the purchase.
    section_text = "\n".join(
        [
            "ANA PAULA S C (final 2673)",
            "@03/02 GOL LINHAS A*QLKLP10/10 119,72 Limite total de crédito 39.360,00",
        ]
    )

    txs, _debug = extract_transactions(section_text, year=2025)

    assert any(
        tx.get("date") == "2025-02-03"
        and abs(tx.get("amount") - 119.72) < 0.001
        and tx.get("cardFinal") == "2673"
        for tx in txs
    )


def test_parse_stops_globally_at_compras_parceladas_even_if_more_blocks_appear_later() -> None:
    text = "\n".join(
        [
            "Vencimento: 01/12/2025",
            "Totaldestafatura 3.760,96",
            "Lanamentos:comprasesaques",
            "30/10 UBER*TRIP 64,21",
            "Compras parceladas - proximas faturas",
            # Everything below must be ignored, even if it looks like valid blocks.
            "Lanamentos:comprasesaques",
            "ANA PAULA S C final2673",
            "03/02 GOLLINHASA*QLKLP10/10 119,72",
        ]
    )

    payload, _warnings, _debug = parse_itau_personnalite(text)
    txs = payload.get("transactions", [])

    assert any(tx.get("date") == "2025-10-30" and abs(tx.get("amount") - 64.21) < 0.001 for tx in txs)
    assert not any("GOLL" in (tx.get("description") or "") for tx in txs)
