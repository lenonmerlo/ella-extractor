from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    """Normalize while keeping line breaks.

    - Removes (cid:N) artifacts
    - Replaces NBSP
    - Normalizes newlines
    - Collapses multiple spaces (not newlines)
    - Trims per-line
    """

    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

    text = re.sub(r"[ \t]{2,}", " ", text)

    lines = [ln.strip() for ln in text.split("\n")]
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
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def _parse_brl_money(amount: str) -> Decimal | None:
    s = (amount or "").strip()
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _infer_year_from_due_date(due: date, month: int) -> int:
    # If transaction month is after due month, it's usually previous year.
    if month > due.month:
        return due.year - 1
    return due.year


_DUE_DATE_RE = re.compile(
    r"(?i)\bvencimento\b\s*(?:em)?\s*[:：-]?\s*(\d{2})/(\d{2})/(\d{4})\b"
)

_DATE_ANYWHERE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")


def extract_due_date(text: str) -> date | None:
    n = _flat(text)
    m = _DUE_DATE_RE.search(n)
    if not m:
        # Fallback: many Bradesco PDFs glue the total and due date in the same visual row,
        # e.g. "... R$ 15.681,84 25/02/2026" after "Total da fatura Vencimento".
        # Try finding a date close to the "Total da fatura" marker.
        anchor = re.search(r"(?i)\btotal\s+da\s+fatura\b", n)
        if anchor:
            tail = n[anchor.end() : anchor.end() + 300]
            m = _DATE_ANYWHERE_RE.search(tail)
        if not m:
            return None

    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


_TOTAL_RE = re.compile(
    r"(?i)\btotal\s+da\s+fatura\b\s*[:：-]?\s*(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b"
)

_TOTAL_FALLBACK_RE = re.compile(
    r"(?i)\btotal\s+da\s+fatura\b.{0,300}?\br\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b"
)


def extract_total(text: str) -> float | None:
    n = _flat(text)
    m = _TOTAL_RE.search(n)
    if not m:
        m = _TOTAL_FALLBACK_RE.search(n)
    if not m:
        return None

    dec = _parse_brl_money(m.group(1))
    if dec is None:
        return None

    return float(dec.quantize(Decimal("0.01")))


_SECTION_START_LANCAMENTOS = re.compile(r"(?i)\blan[cç]amentos\b")
_SECTION_START_FATURA = re.compile(r"(?i)\bfatura\s+mensal\b")

_STOP_MARKER_HARD = re.compile(r"(?i)\btotal\s+da\s+fatura\s+em\s+real\b")
_STOP_MARKER_SOFT = re.compile(r"(?i)\bmensagem\s+importante\b")

# Blocks to ignore when they show up interleaved.
_IGNORED_BLOCK_MARKERS = [
    re.compile(r"(?i)\bcentral\s+de\s+atendimento\b"),
    re.compile(r"(?i)\bmensagem\s+importante\b"),
    re.compile(r"(?i)\btaxas\b"),
    re.compile(r"(?i)\btotal\s+parcelad"),
]

_SKIP_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)^data\s+histo"),
    re.compile(r"(?i)\bhist[oó]rico\s+de\s+lan[cç]amentos\b"),
    re.compile(r"(?i)\bcidade\b"),
    re.compile(r"(?i)^fatura\s+mensal\b"),
    re.compile(r"(?i)^lan[cç]amentos\b"),
    re.compile(r"(?i)^cart[aã]o\b"),
]

_NON_TRANSACTION_PATTERNS: list[re.Pattern[str]] = [
    # Demonstrative payment line (not a purchase transaction)
    re.compile(r"(?i)\bpagto\b|\bpagamento\b"),
    re.compile(r"(?i)\bdeb\s+em\s+c/c\b|\bd[eé]bito\s+em\s+conta\b"),
    # Explanatory IOF text from rate table / legal notes (not a launch)
    re.compile(r"(?i)\bde\s+acordo\s+com\s+a\s+legisla"),
    re.compile(r"(?i)\bsobre\s+as\s+opera[cç][oõ]es\s+de\s+cr[eé]dito\b"),
]

_TX_DATE_PREFIX = re.compile(r"^(?P<dd>\d{2})/(?P<mm>\d{2})\b")
_INSTALLMENT_RE = re.compile(r"\b(?P<cur>\d{2})/(?P<tot>\d{2})\b")
_MONEY_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}")
_MONEY_WITH_SIGN_TRAILING = re.compile(r"(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})(?P<trail>-)\b")

# Lines like: "Encargos sobreparcelado 02/02 10,09" (no leading tx date)
_EMBEDDED_DATE_AND_AMOUNT_RE = re.compile(
    r"^(?P<desc>.+?)\s+(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<amt>\d{1,3}(?:\.\d{3})*,\d{2})$",
    re.IGNORECASE,
)

_TRAILING_GARBAGE_MARKERS: list[re.Pattern[str]] = [
    # Limits/tables glued into transaction lines.
    re.compile(r"(?i)\bsaque\s+r\$(?:\s|$)"),
    re.compile(r"(?i)\btaxas\s+mensais\b"),
    re.compile(r"(?i)\bnovo\s+teto\s+de\s+juros\b"),
    re.compile(r"(?i)\bprograma\s+de\s+fidelidade\b"),
    re.compile(r"(?i)\bpontos\s+acumulados\b"),
    re.compile(r"(?i)\bsaldo\s+de\s+pontos\b"),
    re.compile(r"(?i)\bpagamento\s+de\s+contas\b"),
    re.compile(r"(?i)\bparcelado\s+f[aá]cil\b"),
    re.compile(r"(?i)\bcompras\s+parceladas\b"),
    re.compile(r"(?i)\bcredi[aá]rio\b"),
    re.compile(r"(?i)\brotativo\b"),
    re.compile(r"(?i)\bcentral\s+de\s+atendimento\b"),
    re.compile(r"(?i)\bmensagem\s+importante\b"),
    re.compile(r"(?i)\btotal\s+parcelad"),
    re.compile(r"(?i)\btotal\s+para\s+as\s+pr[oó]ximas\s+faturas\b"),
    # Rate table rows sometimes glue in mid-page.
    re.compile(r"(?i)\bsaque\s+[àa]\s+vista\b"),
    re.compile(r"(?i)\bsaque\s+parcelado\b"),
    re.compile(r"(?i)\*+\s*sobre\s+as\s+opera"),
]

# Up to 4 words (e.g., RIO DE JANEIRO) at the end of line.
_CITY_AT_END_RE = re.compile(r"\b(?P<city>[A-ZÇÃÕÁÉÍÓÚÜ]{3,}(?:\s+[A-ZÇÃÕÁÉÍÓÚÜ]{2,}){0,3})\s*$")


def _slice_transactions_window(text: str) -> tuple[str, dict[str, Any]]:
    normalized = normalize_text(text)
    # Prefer the real transactions section when present.
    m = _SECTION_START_LANCAMENTOS.search(normalized)
    if not m:
        m = _SECTION_START_FATURA.search(normalized)
    if not m:
        return normalized, {
            "windowFound": False,
            "windowStartIndex": None,
            "windowEndIndex": None,
            "windowStartMarker": None,
            "windowEndMarker": None,
        }

    start_idx = m.start()
    start_marker = normalized[m.start() : m.end()]

    # Hard stop: if "Total da fatura em real" exists after start, use it.
    hard = _STOP_MARKER_HARD.search(normalized, pos=start_idx)
    if hard:
        end_idx = hard.start()
        end_marker = normalized[hard.start() : hard.end()]
    else:
        soft = _STOP_MARKER_SOFT.search(normalized, pos=start_idx)
        end_idx = soft.start() if soft else len(normalized)
        end_marker = normalized[soft.start() : soft.end()] if soft else None

    return normalized[start_idx:end_idx].strip(), {
        "windowFound": True,
        "windowStartIndex": start_idx,
        "windowEndIndex": end_idx,
        "windowStartMarker": start_marker,
        "windowEndMarker": end_marker,
    }


def _strip_trailing_garbage_if_needed(compact_line: str) -> str:
    """Strip glued non-transaction blocks appended to a transaction line.

    In some PDFs, the columns/tables (limits, rates) get concatenated to the end of a real
    transaction line. If we don't trim it, amount extraction can pick the wrong number
    (e.g. selecting 15.000,00 from the limits table instead of 580,00 from the purchase).

    Safety: only trims at markers *after* at least one monetary token already appeared.
    This avoids breaking a potential legitimate cash-withdraw transaction that begins
    with something like "SAQUE R$ ...".
    """

    s = (compact_line or "").strip()
    if not s:
        return s

    # Only trim when we already have money earlier in the line.
    money_m = _MONEY_RE.search(s)
    if not money_m:
        return s

    earliest_idx: int | None = None
    for p in _TRAILING_GARBAGE_MARKERS:
        m = p.search(s)
        if not m:
            continue
        if m.start() <= money_m.start():
            # Marker appears before the first money token; don't trim.
            continue
        if earliest_idx is None or m.start() < earliest_idx:
            earliest_idx = m.start()

    return s[:earliest_idx].rstrip() if earliest_idx is not None else s


def _is_non_transaction_description(compact_line: str) -> bool:
    if not compact_line:
        return True
    return any(p.search(compact_line) for p in _NON_TRANSACTION_PATTERNS)


def _looks_like_tx_candidate(compact_line: str) -> bool:
    if not compact_line:
        return False
    return bool(_TX_DATE_PREFIX.match(compact_line) or _EMBEDDED_DATE_AND_AMOUNT_RE.match(compact_line))


def parse_bradesco_fatura_mensal_v1(text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
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

    window, window_debug = _slice_transactions_window(normalized_full)
    if window_debug.get("windowFound") is False:
        warnings.append("transactions_section_not_found_fallback_used")

    txs: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    skipped_block = False

    def add_unmatched(line_text: str, reason: str) -> None:
        if not line_text:
            return
        if len(unmatched) >= 80:
            return
        unmatched.append({"line": line_text, "reason": reason})

    for raw_line in window.split("\n"):
        line = (raw_line or "").strip()
        if not line:
            continue

        if _STOP_MARKER_HARD.search(line):
            break

        if any(p.search(line) for p in _SKIP_LINE_PATTERNS):
            continue

        compact = re.sub(r"\s+", " ", line).strip()
        # Bradesco sometimes prints negative amounts as trailing '-' (e.g. 16.044,43-)
        compact = _MONEY_WITH_SIGN_TRAILING.sub(r"-\g<val>", compact)

        compact = _strip_trailing_garbage_if_needed(compact)

        is_tx_candidate = _looks_like_tx_candidate(compact)

        if _is_non_transaction_description(compact):
            if is_tx_candidate:
                add_unmatched(compact, "non_transaction_line")
            continue

        if any(p.search(compact) for p in _IGNORED_BLOCK_MARKERS):
            skipped_block = True
            continue

        # If we're skipping an ignored block, resume only when we see a tx-like line.
        boolean_tx_like = _TX_DATE_PREFIX.match(compact) or _EMBEDDED_DATE_AND_AMOUNT_RE.match(compact)
        if skipped_block and not boolean_tx_like:
            continue
        if skipped_block and boolean_tx_like:
            skipped_block = False

        dm = _TX_DATE_PREFIX.match(compact)
        if not dm:
            # Support fee lines like "Encargos sobreparcelado 02/02 10,09".
            em = _EMBEDDED_DATE_AND_AMOUNT_RE.match(compact)
            if not em:
                if is_tx_candidate:
                    add_unmatched(compact, "candidate_not_parsed")
                continue

            dd = int(em.group("dd"))
            mm = int(em.group("mm"))
            amount_dec = _parse_brl_money(em.group("amt"))
            if amount_dec is None:
                add_unmatched(compact, "invalid_amount")
                continue

            description = re.sub(r"\s+", " ", (em.group("desc") or "").strip()).strip(" -")
            if not description:
                add_unmatched(compact, "empty_description")
                continue

            tx_year = _infer_year_from_due_date(due, mm) if due else date.today().year
            try:
                tx_date = date(tx_year, mm, dd)
            except ValueError:
                add_unmatched(compact, "invalid_date")
                continue

            txs.append(
                {
                    "date": tx_date.isoformat(),
                    "description": description,
                    "amount": float(amount_dec.quantize(Decimal("0.01"))),
                    "city": None,
                    "installmentCurrent": None,
                    "installmentTotal": None,
                }
            )
            continue

        amounts = _MONEY_RE.findall(compact)
        if not amounts:
            if is_tx_candidate:
                add_unmatched(compact, "no_amount_found")
            continue

        dd = int(dm.group("dd"))
        mm = int(dm.group("mm"))

        # Heuristic: pick the largest absolute monetary value in the line.
        # This avoids capturing fee/percentage-related tokens like "5,49%".
        amount_candidates: list[Decimal] = []
        for a in amounts:
            d = _parse_brl_money(a)
            if d is not None:
                amount_candidates.append(d)
        if not amount_candidates:
            add_unmatched(compact, "invalid_amount")
            continue
        amount_dec = max(amount_candidates, key=lambda d: abs(d))
        if amount_dec is None:
            continue

        # Remove date prefix and trailing amount.
        rest = _TX_DATE_PREFIX.sub("", compact, count=1).strip()
        # Remove the chosen amount occurrence from the end (tolerant).
        chosen_amt_str = None
        for a in amounts:
            d = _parse_brl_money(a)
            if d is not None and d == amount_dec:
                chosen_amt_str = a
        if chosen_amt_str is None:
            chosen_amt_str = amounts[-1]

        idx = rest.rfind(chosen_amt_str)
        if idx >= 0:
            rest_wo_amt = (rest[:idx] + rest[idx + len(chosen_amt_str) :]).strip()
        else:
            rest_wo_amt = rest

        inst_cur: int | None = None
        inst_tot: int | None = None
        # Installment fraction is usually close to the merchant name, but must not match dates like 11/02/2026.
        inst_m = None
        for m_inst in _INSTALLMENT_RE.finditer(rest_wo_amt):
            # Reject if it's immediately followed by '/20xx' (date)
            tail = rest_wo_amt[m_inst.end() :]
            if tail.lstrip().startswith("/20"):
                continue
            inst_m = m_inst
            break

        if inst_m:
            try:
                inst_cur = int(inst_m.group("cur"))
                inst_tot = int(inst_m.group("tot"))
            except ValueError:
                inst_cur = None
                inst_tot = None

        # City (when present) tends to be the last uppercase column.
        city: str | None = None
        city_m = _CITY_AT_END_RE.search(rest_wo_amt)
        if city_m:
            city = city_m.group("city").strip()
            desc_part = rest_wo_amt[: city_m.start()].strip()
            # Guard: when line is all-uppercase, regex may swallow the full merchant text as city.
            # In this case keep full text as description and drop city extraction.
            if not desc_part:
                city = None
                desc_part = rest_wo_amt
        else:
            desc_part = rest_wo_amt

        # Remove installment token from description when it exists.
        if inst_m:
            desc_part = re.sub(r"\s+" + re.escape(inst_m.group(0)) + r"\s+", " ", f" {desc_part} ").strip()

        description = re.sub(r"\s+", " ", desc_part).strip(" -")
        if not description:
            add_unmatched(compact, "empty_description")
            continue

        tx_year = _infer_year_from_due_date(due, mm) if due else date.today().year
        try:
            tx_date = date(tx_year, mm, dd)
        except ValueError:
            add_unmatched(compact, "invalid_date")
            continue

        tx: dict[str, Any] = {
            "date": tx_date.isoformat(),
            "description": description,
            "amount": float(amount_dec.quantize(Decimal("0.01"))),
            "city": city,
            "installmentCurrent": inst_cur,
            "installmentTotal": inst_tot,
        }
        txs.append(tx)

    if not txs:
        warnings.append("transactions_not_found")

    debug: dict[str, Any] = {
        "rawTextLength": raw_len,
        "normalizedTextLength": norm_len,
        **window_debug,
        "transactionsCount": len(txs),
        "sampleLines": [ln for ln in window.split("\n") if ln][:12],
    }

    signed_sum = round(sum(float(t.get("amount", 0) or 0) for t in txs), 2)
    expenses_total = round(sum(float(t.get("amount", 0) or 0) for t in txs if float(t.get("amount", 0) or 0) > 0), 2)
    credits_total_abs = round(sum(abs(float(t.get("amount", 0) or 0)) for t in txs if float(t.get("amount", 0) or 0) < 0), 2)

    reconciliation_diff = None
    is_balanced = None
    if total is not None:
        reconciliation_diff = round(float(total) - signed_sum, 2)
        is_balanced = abs(reconciliation_diff) <= 0.01

    result: dict[str, Any] = {
        "parserContractVersion": "1.0.0",
        "bank": "bradesco_fatura_mensal_v1",
        "dueDate": (due.isoformat() if due else None),
        "total": total,
        "transactions": txs,
        "summary": {
            "invoiceTotal": total,
            "expensesTotal": expenses_total,
            "creditsTotalAbs": credits_total_abs,
            "signedTransactionsTotal": signed_sum,
            "transactionCount": len(txs),
        },
        "reconciliation": {
            "difference": reconciliation_diff,
            "isBalanced": is_balanced,
            "threshold": 0.01,
        },
        "diagnostics": {
            "sourceParser": "parsers.invoices.bradesco_fatura_mensal_v1",
            "notes": [
                "Contract v1 is additive and backward-compatible.",
                "Top-level fields bank/dueDate/total/transactions are preserved.",
            ],
        },
        "unmatchedTransactions": unmatched,
        "warnings": warnings,
        "debug": debug,
    }

    return result, warnings, debug
