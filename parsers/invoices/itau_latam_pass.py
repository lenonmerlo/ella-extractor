from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")

_DESC_LONG_NUMERIC = re.compile(r"\b\d{8,}\b")
_DESC_LONG_ALNUM_WITH_DIGIT = re.compile(r"\b(?=[A-Z0-9]{10,}\b)(?=.*\d)[A-Z0-9]+\b")


def summarize_description(description: str, *, max_len: int = 80) -> str:
    s = re.sub(r"\s+", " ", (description or "").strip())
    if not s:
        return ""

    # Remove common noisy artifacts while trying to keep merchant name.
    s = _DESC_LONG_NUMERIC.sub("", s)
    s = _DESC_LONG_ALNUM_WITH_DIGIT.sub("", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -/|")

    if len(s) <= max_len:
        return s

    # Prefer splitting on separators when present.
    for sep in (" - ", " / ", " | "):
        if sep in s:
            head = s.split(sep, 1)[0].strip()
            if 10 <= len(head) <= max_len:
                return head

    cut = s[:max_len]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.strip()


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


def extract_due_date(text: str) -> date | None:
    n = _flat(text)

    m = re.search(
        r"(?i)\b(?:com\s+vencimento\s+em|vencimento)\s*(?:em)?\s*[:：]?\s*(\d{2})/(\d{2})/(\d{4})\b",
        n,
    )
    if not m:
        return None

    dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        return date(yyyy, mm, dd)
    except ValueError:
        return None


def extract_total(text: str) -> float | None:
    n = _flat(text)

    m = re.search(
        r"(?i)\bo\s+total\s+da\s+sua\s+fatura\s*[ée]\s*[:：]?\s*(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b",
        n,
    )
    if not m:
        m = re.search(
            r"(?i)\btotal\s+desta\s+fatura\s*(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b",
            n,
        )
    if not m:
        return None

    dec = _parse_brl_money(m.group(1))
    if dec is None:
        return None

    return float(dec.quantize(Decimal("0.01")))


_SECTION_START = re.compile(
    r"(?is)lan\s*(?:c|ç)?\s*amentos\s*[:：]?\s*compras\s*e\s*saques"
)
_SECTION_PRODUCTS = re.compile(
    r"(?is)lan\s*(?:c|ç)?\s*amentos\s*[:：]?\s*produtos\s*e\s*servi"
)

_STOP_MARKER = re.compile(
    r"(?is)(compras\s*parceladas\s*-\s*pr[oó]ximas\s*faturas|compras\s*parceladas|pr[oó]xima\s*fatura|demais\s*faturas|total\s+para\s+proximas\s+faturas)"
)

_ENCARGOS_HEADER = re.compile(r"(?i)^encargos\s+cobrados\s+nesta\s+fatura\b")

_SKIP_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)^data\s+estabelecimento\s+valor\s+em\s+r\$"),
    re.compile(r"(?i)^data\s+estabelecimento\s+valor\b"),
    re.compile(r"(?i)^limites\s+de\s+cr[eé]dito\b"),
    re.compile(r"(?i)^limite\s+(?:total|dispon[íi]vel|total\s+utilizado)\b"),
    re.compile(r"(?i)^esses\s+s[aã]o\s+os\s+seus\s+limites\b"),
    re.compile(r"(?i)^caso\s+queira\s+consultar\b"),
    re.compile(r"(?i)^lan\s*(?:c|ç)?\s*amentos\b"),
]


def _slice_transactions_window(text: str) -> tuple[str, dict[str, Any]]:
    normalized = normalize_text(text)

    start_match = _SECTION_START.search(normalized)
    products_match = _SECTION_PRODUCTS.search(normalized)

    if start_match:
        start_idx = start_match.start()
        start_marker = normalized[start_match.start() : start_match.end()]
    elif products_match:
        start_idx = products_match.start()
        start_marker = normalized[products_match.start() : products_match.end()]
    else:
        return normalized, {
            "windowFound": False,
            "windowStartIndex": None,
            "windowEndIndex": None,
            "windowStartMarker": None,
            "windowEndMarker": None,
        }

    stop = _STOP_MARKER.search(normalized, pos=start_idx)
    end_idx = stop.start() if stop else len(normalized)
    end_marker = normalized[stop.start() : stop.end()] if stop else None

    return normalized[start_idx:end_idx].strip(), {
        "windowFound": True,
        "windowStartIndex": start_idx,
        "windowEndIndex": end_idx,
        "windowStartMarker": start_marker,
        "windowEndMarker": end_marker,
    }


_TX_WITH_INSTALLMENT = re.compile(
    r"^(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<desc>.+?)\s+(?P<inst_cur>\d{2})/(?P<inst_total>\d{2})\s+(?P<amount>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}))(?:\s+.*)?$"
)
_TX_NO_INSTALLMENT = re.compile(
    r"^(?P<dd>\d{2})/(?P<mm>\d{2})\s+(?P<desc>.+?)\s+(?P<amount>-?(?:\d{1,3}(?:\.\d{3})*,\d{2}|\d+,\d{2}))(?:\s+.*)?$"
)
_DATE_PREFIX = re.compile(r"^\d{2}/\d{2}\b")


def parse_itau_latam_pass(text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
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

    window, window_debug = _slice_transactions_window(normalized_full)
    if window_debug.get("windowFound") is False:
        warnings.append("transactions_section_not_found_fallback_used")

    txs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    join_count = 0
    dropped_continuations = 0

    skipping_encargos = False

    for raw_line in window.split("\n"):
        line = (raw_line or "").strip()
        if not line:
            continue

        if _STOP_MARKER.search(line):
            break

        low = line.lower()
        if "pagamentos efetuados" in low:
            continue

        if _ENCARGOS_HEADER.search(line):
            skipping_encargos = True
            continue

        if skipping_encargos:
            if _SECTION_START.search(line) or _SECTION_PRODUCTS.search(line):
                skipping_encargos = False
            else:
                continue

        if any(p.search(line) for p in _SKIP_LINE_PATTERNS):
            continue

        compact = re.sub(r"\s+", " ", line).strip()

        m = _TX_WITH_INSTALLMENT.match(compact)
        inst_cur: int | None = None
        inst_total: int | None = None
        if m:
            inst_cur = int(m.group("inst_cur"))
            inst_total = int(m.group("inst_total"))
        else:
            m = _TX_NO_INSTALLMENT.match(compact)

        if m:
            if current is not None:
                txs.append(current)
                current = None

            dd = int(m.group("dd"))
            mm = int(m.group("mm"))
            desc = summarize_description((m.group("desc") or "").strip())
            amount_dec = _parse_brl_money(m.group("amount"))
            if amount_dec is None:
                continue

            try:
                tx_date = date(tx_year, mm, dd)
            except ValueError:
                continue

            current = {
                "date": tx_date.isoformat(),
                "description": desc,
                "amount": float(amount_dec.quantize(Decimal("0.01"))),
            }
            if inst_cur is not None and inst_total is not None:
                current["installmentCurrent"] = inst_cur
                current["installmentTotal"] = inst_total

            continue

        # Continuation line: join to previous description.
        if _DATE_PREFIX.search(compact):
            # Looks like a date but didn't match tx pattern; ignore.
            continue

        # Ignore obvious section-ish headers
        if compact.lower().startswith("lançamentos") or compact.lower().startswith("lancamentos"):
            continue

        if current is None:
            dropped_continuations += 1
            continue

        current["description"] = summarize_description(f"{current.get('description','')} {compact}".strip())
        join_count += 1

    if current is not None:
        txs.append(current)

    debug: dict[str, Any] = {
        "rawTextLength": raw_len,
        "normalizedTextLength": norm_len,
        **window_debug,
        "transactionsCount": len(txs),
        "joinedContinuationLines": join_count,
        "droppedContinuationLines": dropped_continuations,
        "sampleLines": [ln for ln in window.split("\n") if ln][:12],
    }

    result: dict[str, Any] = {
        "bank": "itau_latam_pass",
        "dueDate": (due.isoformat() if due else None),
        "total": total,
        "transactions": txs,
        "warnings": warnings,
        "debug": debug,
    }

    return result, warnings, debug
