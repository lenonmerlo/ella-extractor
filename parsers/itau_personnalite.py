from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable


_CID_PATTERN = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    """Normalize while keeping line breaks.

    - Removes (cid:N) artifacts
    - Replaces NBSP
    - Collapses multiple spaces (not newlines)
    - Trims per-line
    """
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

    # Collapse repeated spaces/tabs but keep newlines
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Trim each line
    lines = [ln.strip() for ln in text.split("\n")]

    # Remove excessive blank lines
    out: list[str] = []
    blank_run = 0
    for ln in lines:
        if not ln:
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        out.append(ln)

    return "\n".join(out).strip()


def _flat(text: str) -> str:
    """Flatten to a single line for easier searching."""
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def extract_due_date(text: str) -> date | None:
    n = _flat(text)
    m = re.search(r"(?i)\bvencimento\s*:\s*(\d{2})/(\d{2})/(\d{4})\b", n)
    if not m:
        return None
    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


def _parse_brl_money(value: str) -> Decimal | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    # Keep digits, separators and sign
    s = re.sub(r"[^0-9,\.\-]", "", s)
    # Remove thousands separators and turn comma into dot
    s = s.replace(".", "").replace(",", ".")

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def extract_total(text: str) -> float | None:
    n = _flat(text)
    # Ordered fallbacks (some PDFs glue words like "Totaldestafatura")
    patterns: list[re.Pattern[str]] = [
        # Totaldestafatura 3.760,96  (also matches "Total desta fatura")
        re.compile(
            r"(?i)total\s*desta\s*fatura\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"
        ),
        # Ototaldasuafatura: R$ 3.760,96 (also matches spaced version)
        re.compile(
            r"(?i)o\s*total\s*da\s*sua\s*fatura\s*:\s*r\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"
        ),
        # fallback: Lanamentosatuais 3.760,96 (also matches spaced / with cedilla)
        re.compile(
            r"(?i)lan\s*(?:c|ç)?\s*amentos\s*atuais\s+([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"
        ),
    ]

    d: Decimal | None = None
    for pat in patterns:
        m = pat.search(n)
        if not m:
            continue
        d = _parse_brl_money(m.group(1))
        if d is not None:
            break

    if d is None:
        return None
    return float(d.quantize(Decimal("0.01")))


@dataclass
class SectionDebug:
    sectionFound: bool
    sectionStartIndex: int | None
    sectionEndIndex: int | None
    startMarker: str | None
    endMarker: str | None


_LAUNCHES_START = re.compile(
    r"(?is)lan\s*(?:c|ç)?\s*amentos\s*[:：]?\s*compras\s*e\s*saques"
)

_END_MARKER = re.compile(
    r"(?is)(encargos\s*cobrados\s*nesta\s*fatura|encargoscobradosnestafatura|compras\s*parceladas|limites\s*de\s*cr[eé]dito|juros\s*do\s*rotativo|novo\s*teto\s*de\s*juros|cr[eé]dito\s*rotativo)"
)

# Mandatory stop markers for excluding "Compras parceladas - próximas faturas".
_PARCELADAS_STOP = re.compile(
    r"(?is)(compras\s*parceladas\s*-\s*pr[oó]?ximas\s*faturas|comprasparceladas\s*-?\s*pr[oó]?ximasfaturas|compras\s*parceladas|comprasparceladas|simula\w*compras\w*parc)"
)

_CARD_HEADER_FINAL = re.compile(
    r"(?i)(?:\(|\b)\s*final\s*(\d{4})\s*(?:\)|\b)"
)


def slice_transactions_sections(text: str) -> tuple[list[str], dict[str, Any]]:
    """Return (sections, debug_dict).

    Finds *all* occurrences of the "Lançamentos: compras e saques" blocks and slices each
    block exclusively before the first stop marker.
    """

    normalized = normalize_text(text)

    # State machine window:
    # SEARCH_START -> first "Lançamentos: compras e saques"
    # READ_TRANSACTIONS -> parse only within window
    # STOP -> first "Compras parceladas" marker (exclusive)
    window_start_match = _LAUNCHES_START.search(normalized)
    if not window_start_match:
        return [normalized], {
            "windowFound": False,
            "windowStartIndex": None,
            "windowEndIndex": None,
            "windowStartMarker": None,
            "windowEndMarker": None,
            "sectionsFound": False,
            "sectionsCount": 0,
            "sections": [],
        }

    window_start = window_start_match.start()
    parceladas_match = _PARCELADAS_STOP.search(normalized, pos=window_start_match.end())
    window_end = parceladas_match.start() if parceladas_match else len(normalized)

    window_text = normalized[window_start:window_end]

    starts = list(_LAUNCHES_START.finditer(window_text))
    if not starts:
        # Should not happen because window is built from a start marker, but keep safe.
        return [window_text], {
            "windowFound": True,
            "windowStartIndex": window_start,
            "windowEndIndex": window_end,
            "windowStartMarker": normalized[
                window_start_match.start() : window_start_match.end()
            ],
            "windowEndMarker": (
                normalized[parceladas_match.start() : parceladas_match.end()]
                if parceladas_match
                else None
            ),
            "sectionsFound": False,
            "sectionsCount": 0,
            "sections": [],
        }

    sections: list[str] = []
    sections_debug: list[dict[str, Any]] = []

    for idx, block_start_match in enumerate(starts):
        start = block_start_match.start()
        per_block_window_end = (
            starts[idx + 1].start() if idx + 1 < len(starts) else len(window_text)
        )

        # Search stop markers inside this window. "Compras parceladas" markers are mandatory.
        end_candidates: list[tuple[int, str]] = []

        parceladas_match = _PARCELADAS_STOP.search(
            window_text, pos=block_start_match.end(), endpos=per_block_window_end
        )
        if parceladas_match:
            end_candidates.append(
                (
                    parceladas_match.start(),
                    window_text[
                        parceladas_match.start() : parceladas_match.end()
                    ],
                )
            )

        end_match = _END_MARKER.search(
            window_text, pos=block_start_match.end(), endpos=per_block_window_end
        )
        if end_match:
            end_candidates.append(
                (end_match.start(), window_text[end_match.start() : end_match.end()])
            )

        if end_candidates:
            end, end_marker = min(end_candidates, key=lambda t: t[0])
        else:
            end, end_marker = per_block_window_end, None

        section = window_text[start:end].strip()
        if section:
            sections.append(section)

        sections_debug.append(
            {
                "sectionFound": True,
                "sectionStartIndex": start,
                "sectionEndIndex": end,
                "startMarker": window_text[
                    block_start_match.start() : block_start_match.end()
                ],
                "endMarker": end_marker,
            }
        )

    return sections, {
        "windowFound": True,
        "windowStartIndex": window_start,
        "windowEndIndex": window_end,
        "windowStartMarker": normalized[
            window_start_match.start() : window_start_match.end()
        ],
        "windowEndMarker": (
            normalized[parceladas_match.start() : parceladas_match.end()]
            if parceladas_match
            else None
        ),
        "sectionsFound": True,
        "sectionsCount": len(sections),
        "sections": sections_debug,
    }


def slice_transactions_section(text: str) -> tuple[str, dict[str, Any]]:
    """Backward-compatible wrapper returning the first section only."""

    sections, debug = slice_transactions_sections(text)
    if debug.get("sectionsFound") is False:
        return sections[0], {
            "sectionFound": False,
            "sectionStartIndex": None,
            "sectionEndIndex": None,
            "startMarker": None,
            "endMarker": None,
        }

    first_debug = (debug.get("sections") or [{}])[0]
    return (sections[0] if sections else ""), {
        "sectionFound": True,
        "sectionStartIndex": first_debug.get("sectionStartIndex"),
        "sectionEndIndex": first_debug.get("sectionEndIndex"),
        "startMarker": first_debug.get("startMarker"),
        "endMarker": first_debug.get("endMarker"),
    }


_SKIP_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)^data\s+estabelecimento\s+valor\s+em\s+r\$"),
    re.compile(r"(?i)^data\s+estabelecimento\s+valor"),
    re.compile(r"(?i)^lan\s*(?:c|ç)?\s*amentos\b"),
    re.compile(r"(?i)^total\s+dos\s+lan\s*(?:c|ç)?\s*amentos\s+atuais\b"),
    re.compile(r"(?i)^proxima\s+fatura\b"),
    re.compile(r"(?i)^demais\s+faturas\b"),
    re.compile(r"(?i)^total\s+para\s+proximas\s+faturas\b"),
]


def _looks_like_category_line(line: str) -> bool:
    # e.g. "SAUDE .FORTALEZA" / "VESTUARIO .SAO PAULO" (no dd/mm, no amount)
    if not line:
        return False
    if re.search(r"\d", line):
        return False
    if "." not in line:
        return False
    # avoid skipping normal merchant lines with punctuation but no digits (rare) –
    # category lines are usually short and uppercase-ish
    return len(line) <= 40


_TX_LINE = re.compile(
    r"^(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<desc>.+?)\s+(?P<amount>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}))\s*$"
)

_TX_LINE_AFTER_CARD_HEADER = re.compile(
    r"\)\s*(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<desc>.+?)\s+(?P<amount>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}))\s*$"
)

_TX_PREFIX_BEFORE_AMOUNT = re.compile(
    r"^(?:.*?\)\s*)?(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<desc>.+)$"
)

_DATE_TX_START = re.compile(
    r"(?:^|\s)(\d{2}/\d{2})(?=\s+[A-ZÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ])"
)

_MONEY_AT_END = re.compile(r"-?\d+(?:\.\d{3})*,\d{2}\s*$")
_MONEY_ANY = re.compile(r"-?\d+(?:\.\d{3})*,\d{2}")
_ONLY_DATE_AND_MONEY = re.compile(r"^\d{2}/\d{2}\s+-?\d+(?:\.\d{3})*,\d{2}$")

_FRACTION_BEFORE_AMOUNT = re.compile(
    r"(\d{1,2}/\d{1,2})(?=\d{1,3}(?:\.\d{3})*,\d{2}\b)"
)

_LEADING_JUNK_BEFORE_DATE = re.compile(r"^[^0-9]{1,3}(?=\d{2}/\d{2})")

_CHARGES_HEADER = re.compile(
    r"(?i)^(encargos\s*cobrados\s*nesta\s*fatura|encargoscobradosnestafatura|juros\s*do\s*rotativo|novo\s*teto\s*de\s*juros|cr[eé]dito\s*rotativo)\b"
)

_CHARGES_CUTOFF = re.compile(
    r"(?i)(encargos\s*cobrados\s*nesta\s*fatura|encargoscobradosnestafatura|juros\s*do\s*rotativo|juros|multa|iof|cr[eé]dito\s*rotativo|novo\s*teto)"
)


def _truncate_at_charges_keywords(line: str) -> str:
    """Truncate a contaminated transaction line before charges/interest keywords.

    Some PDFs glue the 'Encargos/Juros/IOF...' block to the end of a valid purchase line,
    causing the last monetary token to become '0,00' and the transaction amount to be parsed
    incorrectly. We only truncate if the prefix ends with a monetary value.
    """

    if not line:
        return line

    m = _CHARGES_CUTOFF.search(line)
    if not m:
        return line

    prefix = line[: m.start()].rstrip()
    if not prefix:
        return line

    # Only apply truncation when the prefix keeps a valid amount at the end.
    if not _MONEY_AT_END.search(prefix):
        return line

    return prefix


def _separate_fraction_from_amount(line: str) -> str:
    """Insert a separator when installment fraction is glued to the amount.

    Example: "...10/10119,72" -> "...10/10 119,72"
    """

    if not line:
        return line
    return _FRACTION_BEFORE_AMOUNT.sub(r"\1 ", line)


def _remove_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)
    )


def _normalize_desc_for_dedupe(desc: str) -> str:
    if not desc:
        return ""
    # Remove installment fractions like 10/10 and normalize for comparisons.
    desc = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", desc)
    desc = _remove_accents(desc).lower()
    return re.sub(r"[^a-z0-9]+", "", desc)


def _descriptions_similar(a: str, b: str) -> bool:
    na = _normalize_desc_for_dedupe(a)
    nb = _normalize_desc_for_dedupe(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    # substring heuristic for "parecida"
    if len(na) >= 5 and na in nb:
        return True
    if len(nb) >= 5 and nb in na:
        return True
    return False


def _dedupe_transactions(txs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by date + amount + similar description.

    If a duplicate provides cardFinal, it is merged into the first occurrence.
    """

    out: list[dict[str, Any]] = []
    for tx in txs:
        tx_date = tx.get("date")
        tx_amount = tx.get("amount")
        tx_desc = tx.get("description") or ""
        if not tx_date or tx_amount is None:
            out.append(tx)
            continue

        merged = False
        for existing in out:
            if existing.get("date") != tx_date:
                continue
            ex_amount = existing.get("amount")
            if ex_amount is None:
                continue
            if abs(float(ex_amount) - float(tx_amount)) > 0.005:
                continue
            if not _descriptions_similar(existing.get("description") or "", tx_desc):
                continue

            # Merge cardFinal if missing.
            if not existing.get("cardFinal") and tx.get("cardFinal"):
                existing["cardFinal"] = tx.get("cardFinal")
            merged = True
            break

        if not merged:
            out.append(tx)

    return out


def extract_card_block_transactions(full_text: str, year: int) -> list[dict[str, Any]]:
    """Extract per-card transactions (block B) based on '(final XXXX)' headers.

    This is resilient to where the card blocks appear in the PDF text; it stops when reaching
    mandatory "Compras parceladas" markers to avoid parsing future installments.
    """

    normalized = normalize_text(full_text)
    lines = [ln.strip() for ln in normalized.split("\n")]

    out: list[dict[str, Any]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue

        # Stop scanning if the PDF enters the "Compras parceladas" area.
        if _PARCELADAS_STOP.search(line):
            break

        m = _CARD_HEADER_FINAL.search(line)
        if not m:
            i += 1
            continue

        # Build a mini-section that starts at this card header and continues until the next card header
        # or until we hit parceladas/other section stops.
        block_lines: list[str] = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i]
            if not nxt:
                i += 1
                continue
            if _PARCELADAS_STOP.search(nxt):
                break
            if _CARD_HEADER_FINAL.search(nxt):
                break
            if _CHARGES_HEADER.search(nxt):
                break
            block_lines.append(nxt)
            i += 1

        block_text = "\n".join(block_lines)
        block_txs, _debug = extract_transactions(block_text, year)
        out.extend(block_txs)

    return out


def _split_candidates_tx_start(line: str) -> list[int]:
    """Return split indices (start positions) for transaction-start dates.

    We only consider dates that look like the *start of a transaction*, i.e.
    dd/MM followed by whitespace and an uppercase letter (merchant).
    This avoids false splits on installment fractions inside descriptions, e.g.
    "11/06 MERCHANT 06/06 55,96".
    """

    if not line:
        return []

    indices: list[int] = []
    for m in _DATE_TX_START.finditer(line):
        indices.append(m.start(1))
    return indices


def _is_valid_split_segment(segment: str) -> bool:
    s = (segment or "").strip()
    if not s:
        return False

    s = _trim_to_last_money(s)

    # Must contain (and effectively end at) a BRL monetary value
    if not _MONEY_AT_END.search(s):
        return False
    # Drop installment-like segments produced by bad splits: "dd/MM 55,96"
    if _ONLY_DATE_AND_MONEY.fullmatch(s):
        return False
    return True


def _trim_to_last_money(line: str) -> str:
    """Trim a line to end at the last BRL monetary token.

    pdfplumber column reconstruction can glue trailing text (e.g. city/category) after the amount,
    which would make strict end-of-line matching fail. This keeps parsing stable without becoming
    overly permissive.
    """

    if not line:
        return line

    low = line.lower()
    # If the transaction line was glued with the "Limites de crédito" block, cut at the first
    # occurrence of "limite" so we don't accidentally pick the credit limit value.
    cut = low.find("limite")
    if cut != -1:
        prefix = line[:cut].rstrip()
        prefix_matches = list(_MONEY_ANY.finditer(prefix))
        if prefix_matches:
            last = prefix_matches[-1]
            return prefix[: last.end()].rstrip()
        return prefix

    matches = list(_MONEY_ANY.finditer(line))
    if not matches:
        return line

    last = matches[-1]
    return line[: last.end()].rstrip()


def _split_multi_tx_line(line: str) -> tuple[list[str], list[str]]:
    """Split a line that may contain 2+ transactions.

    Example:
      "19/05 ... 500,00 30/10 ... 19,54" ->
      ["19/05 ... 500,00", "30/10 ... 19,54"]
    """

    if not line:
        return [], []

    split_indices = _split_candidates_tx_start(line)
    if len(split_indices) <= 1:
        return [line], []

    raw_segments: list[str] = []
    for idx, start in enumerate(split_indices):
        end = split_indices[idx + 1] if idx + 1 < len(split_indices) else len(line)
        seg = line[start:end].strip()
        if seg:
            raw_segments.append(seg)

    kept: list[str] = []
    dropped: list[str] = []
    for seg in raw_segments:
        trimmed = _trim_to_last_money(seg).strip()
        if _is_valid_split_segment(trimmed):
            kept.append(trimmed)
        else:
            dropped.append(seg)

    # If filtering left us with only one segment, treat as unsplit.
    if len(kept) <= 1:
        return [line], dropped

    return kept, dropped


def extract_transactions(section_text: str, year: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not section_text:
        return out, {
            "splitLinesCount": 0,
            "splitExamples": [],
            "droppedSegmentsCount": 0,
            "droppedSegmentsExamples": [],
        }

    normalized = normalize_text(section_text)

    # Debug counters (returned via parse_itau_personnalite -> debug)
    split_lines_count = 0
    split_examples: list[dict[str, Any]] = []
    dropped_segments_count = 0
    dropped_segments_examples: list[dict[str, Any]] = []

    current_card_final: str | None = None

    for raw_line in normalized.split("\n"):
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Some extracted lines may include bullets/markers like "@03/02".
        raw_line = _LEADING_JUNK_BEFORE_DATE.sub("", raw_line).strip()
        if not raw_line:
            continue

        raw_line = _separate_fraction_from_amount(raw_line)

        # Hard stop: charges/interest blocks are not purchases and often contaminate nearby lines.
        if _CHARGES_HEADER.search(raw_line):
            break

        # Keep track of current card final when present (ignore holder name; accept many formats).
        # Examples: "ANAPAULASC(final8578)", "ANA PAULA S C (final 2673)", "final2673".
        m_final = _CARD_HEADER_FINAL.search(raw_line)
        if m_final:
            current_card_final = m_final.group(1)

        raw_line = _truncate_at_charges_keywords(raw_line)
        if not raw_line:
            continue

        segments, dropped_segments = _split_multi_tx_line(raw_line)
        if len(segments) > 1:
            split_lines_count += 1
            if len(split_examples) < 5:
                split_examples.append({"original": raw_line, "segments": segments})

        if dropped_segments:
            dropped_segments_count += len(dropped_segments)
            if len(dropped_segments_examples) < 5:
                dropped_segments_examples.append(
                    {"original": raw_line, "dropped": dropped_segments}
                )

        for line in segments:
            compact_line = re.sub(r"\s+", " ", line).strip()
            compact_line = _LEADING_JUNK_BEFORE_DATE.sub("", compact_line).strip()
            compact_line = _separate_fraction_from_amount(compact_line)
            compact_line = _trim_to_last_money(compact_line)
            nline = compact_line.lower()

            if any(p.search(nline) for p in _SKIP_LINE_PATTERNS):
                continue
            if _looks_like_category_line(line):
                continue

            m = _TX_LINE.match(compact_line)
            if not m:
                m = _TX_LINE_AFTER_CARD_HEADER.search(compact_line)
            if not m:
                # Fallback: amount may be glued to the description (missing whitespace).
                m_amount = _MONEY_AT_END.search(compact_line)
                if not m_amount:
                    continue

                amount_str = m_amount.group(0).strip()
                prefix = compact_line[: m_amount.start()].rstrip()

                m_prefix = _TX_PREFIX_BEFORE_AMOUNT.match(prefix)
                if not m_prefix:
                    continue

                dd = int(m_prefix.group("dd"))
                mm = int(m_prefix.group("mm"))
                desc = m_prefix.group("desc").strip()

                if not re.search(r"[A-Za-zÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ]", desc):
                    continue

                # Clean installment fraction like "07/10" which can be glued to the merchant
                desc = re.sub(r"\d{1,2}/\d{1,2}\b", " ", desc)
                desc = re.sub(r"\s+", " ", desc).strip()

                amount_dec = _parse_brl_money(amount_str)
                if amount_dec is None:
                    continue

                if "limite" in desc.lower() and amount_dec.copy_abs() >= Decimal("2000"):
                    continue

                if (
                    "proxima fatura" in desc.lower()
                    or "próxima fatura" in desc.lower()
                    or "demais faturas" in desc.lower()
                    or "total para proximas faturas" in desc.lower()
                ):
                    continue

                try:
                    tx_date = date(year, mm, dd)
                except ValueError:
                    continue

                out.append(
                    {
                        "date": tx_date.isoformat(),
                        "description": desc,
                        "amount": float(amount_dec.quantize(Decimal("0.01"))),
                        **(
                            {"cardFinal": current_card_final}
                            if current_card_final
                            else {}
                        ),
                    }
                )
                continue

            dd = int(m.group("dd"))
            mm = int(m.group("mm"))
            desc = m.group("desc").strip()

            # Clean installment fraction like "07/10" which can be glued to the merchant
            desc = re.sub(r"\b\d{1,2}/\d{1,2}\b", " ", desc)
            desc = re.sub(r"\s+", " ", desc).strip()

            amount_dec = _parse_brl_money(m.group("amount"))
            if amount_dec is None:
                continue

            # Guardrail: ignore "Limite"-looking lines when amount is huge and likely a credit limit.
            if "limite" in desc.lower() and amount_dec.copy_abs() >= Decimal("2000"):
                continue

            # Ignore lines that are clearly summary, even if they match the tx regex
            if "proxima fatura" in desc.lower() or "demais faturas" in desc.lower() or "total para proximas faturas" in desc.lower():
                continue

            try:
                tx_date = date(year, mm, dd)
            except ValueError:
                continue

            out.append(
                {
                    "date": tx_date.isoformat(),
                    "description": desc,
                    "amount": float(amount_dec.quantize(Decimal("0.01"))),
                    **({"cardFinal": current_card_final} if current_card_final else {}),
                }
            )

    return out, {
        "splitLinesCount": split_lines_count,
        "splitExamples": split_examples,
        "droppedSegmentsCount": dropped_segments_count,
        "droppedSegmentsExamples": dropped_segments_examples,
    }


def parse_itau_personnalite(text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    warnings: list[str] = []

    raw_len = len(text or "")
    normalized_full = normalize_text(text or "")
    norm_len = len(normalized_full)

    due = extract_due_date(normalized_full)
    if due is None:
        warnings.append("due_date_not_found")

    total = extract_total(normalized_full)
    if total is None:
        warnings.append("total_not_found")

    tx_year = due.year if due else date.today().year

    sections, sections_debug = slice_transactions_sections(normalized_full)
    if sections_debug.get("sectionsFound") is False:
        warnings.append("transactions_section_not_found_fallback_used")

    txs: list[dict[str, Any]] = []
    combined_tx_debug: dict[str, Any] = {
        "splitLinesCount": 0,
        "splitExamples": [],
        "droppedSegmentsCount": 0,
        "droppedSegmentsExamples": [],
    }

    for section in sections:
        block_txs, block_debug = extract_transactions(section, tx_year)
        txs.extend(block_txs)

        combined_tx_debug["splitLinesCount"] += int(block_debug.get("splitLinesCount", 0))
        combined_tx_debug["droppedSegmentsCount"] += int(block_debug.get("droppedSegmentsCount", 0))

        # Keep a few examples overall
        if len(combined_tx_debug.get("splitExamples", [])) < 5:
            combined_tx_debug["splitExamples"].extend(block_debug.get("splitExamples", [])[: 5 - len(combined_tx_debug["splitExamples"])])
        if len(combined_tx_debug.get("droppedSegmentsExamples", [])) < 5:
            combined_tx_debug["droppedSegmentsExamples"].extend(
                block_debug.get("droppedSegmentsExamples", [])[: 5 - len(combined_tx_debug["droppedSegmentsExamples"]) ]
            )

    # Extract per-card blocks (B) only within the global window.
    if sections_debug.get("windowFound"):
        w_start = int(sections_debug.get("windowStartIndex") or 0)
        w_end = int(sections_debug.get("windowEndIndex") or len(normalized_full))
        window_text = normalized_full[w_start:w_end]
    else:
        window_text = normalized_full

    card_block_txs = extract_card_block_transactions(window_text, tx_year)
    txs.extend(card_block_txs)
    txs = _dedupe_transactions(txs)

    debug: dict[str, Any] = {
        "rawTextLength": raw_len,
        "normalizedTextLength": norm_len,
        **sections_debug,
        "transactionsCount": len(txs),
        "sampleLines": [
            ln
            for sec in sections[:1]
            for ln in sec.split("\n")
            if ln
        ][:10],
        **combined_tx_debug,
        "cardBlockTransactionsCount": len(card_block_txs),
    }

    result: dict[str, Any] = {
        "bank": "itau_personnalite",
        "dueDate": (due.isoformat() if due else None),
        "total": total,
        "transactions": txs,
        "warnings": warnings,
        "debug": debug,
    }

    return result, warnings, debug
