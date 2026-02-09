from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    """Normalize extracted PDF text while keeping line breaks."""
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

    # Collapse spaces/tabs, but keep newlines
    text = re.sub(r"[ \t]{2,}", " ", text)

    # Trim each line, keep at most one empty line in a row
    out: list[str] = []
    blank_run = 0
    for ln in (ln.strip() for ln in text.split("\n")):
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


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


_PERIOD_RE = re.compile(
    r"(?i)\bper[ií]odo\b[^0-9]*(\d{2}/\d{2}/\d{4})\s*(?:a|\-|at[eé])\s*(\d{2}/\d{2}/\d{4})"
)

_MOVIMENTACAO_ENTRE_RE = re.compile(
    r"(?i)movimenta[cç][aã]o\s+entre\s*:?\s*(\d{2}/\d{2}/\d{4})\s*(?:e|a|\-|at[eé])\s*(\d{2}/\d{2}/\d{4})"
)

_DATE_DDMMYYYY_RE = re.compile(r"^(?P<dd>\d{2})/(?P<mm>\d{2})/(?P<yyyy>\d{4})\b")
_DATE_DDMM_RE = re.compile(r"^(?P<dd>\d{2})/(?P<mm>\d{2})\b")

# BRL number (optionally +/-, thousands dot, decimal comma)
_MONEY_RE = re.compile(r"(?:(?P<sign>[+\-−])\s*)?(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})\b")

_OPENING_RE = re.compile(
    r"(?i)\b(saldo\s*(?:anterior|inicial))\b[^0-9\-]*(-?\d{1,3}(?:\.\d{3})*,\d{2})"
)
_CLOSING_RE = re.compile(r"(?i)\b(saldo\s*(?:final|atual))\b[^0-9\-]*(-?\d{1,3}(?:\.\d{3})*,\d{2})")


def _parse_date_ddmmyyyy(value: str) -> date | None:
    if not value:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", value.strip())
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

    s = s.replace("−", "-").replace("–", "-").replace("—", "-")

    sign = -1 if s.lstrip().startswith("-") else 1

    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")

    try:
        d = Decimal(s)
    except InvalidOperation:
        return None

    return d * sign


def _extract_money(text: str, pattern: re.Pattern[str]) -> Decimal | None:
    m = pattern.search(_flat(text))
    if not m:
        return None
    return _parse_brl_money(m.group(2))


def looks_like_bradesco_bank_statement(text: str) -> bool:
    n = _strip_accents(_flat(text)).lower()
    if not n:
        return False

    if "bradesco" not in n:
        return False

    # Keep it permissive; PDF headers vary.
    markers = ["extrato", "saldo", "agencia", "agencia:", "conta"]
    return any(m in n for m in markers)


@dataclass(frozen=True)
class _ParsedTx:
    transactionDate: date
    description: str
    amountAbs: Decimal | None
    balance: Decimal | None
    type: str


def _clean_description(desc: str) -> str:
    d = re.sub(r"\s+", " ", (desc or "").strip())
    # Remove obvious column headers that sometimes leak into a line.
    d = re.sub(r"(?i)\b(cr[eé]dito|d[eé]bito|saldo|docto\.?|documento)\b", "", d).strip()
    d = re.sub(r"\s{2,}", " ", d)
    if len(d) > 120:
        d = d[:117].rstrip() + "..."
    return d


def _summarize_description(desc: str) -> str:
    """Produce a shorter, human-friendly description for Bradesco rows.

    The raw PDF extraction can split a single transaction across multiple lines.
    We keep meaningful labels (e.g. TRANSFERENCIA PIX, TED...) plus party markers
    (DES:/REM:/DEST:), while removing numeric columns like docto/values.
    """

    d = _clean_description(desc)
    if not d:
        return d

    # Drop money tokens and standalone dates.
    d = _MONEY_RE.sub("", d)
    d = re.sub(r"\b\d{2}/\d{2}/\d{4}\b", "", d)
    d = re.sub(r"\b\d{2}/\d{2}\b", "", d)

    # Drop likely docto ids (5+ digits) while keeping short codes.
    d = re.sub(r"\b\d{5,}\b", "", d)

    # Remove some boilerplate codes.
    d = re.sub(r"(?i)\bCOD\.?\s*LANC\.?\s*\d+\b", "", d)

    # Collapse repeated history markers commonly duplicated in this layout.
    # e.g. "TRANSFERENCIA PIX ... TRANSFERENCIA PIX" -> keep one
    d = re.sub(r"(?i)\b(TRANSFERENCIA\s+PIX)(?:\s+\1)+\b", r"\1", d)

    # Normalize punctuation-like markers without losing meaning.
    d = re.sub(r"\s{2,}", " ", d).strip(" -|\t")

    # Prefer keeping main label + party info; cut aggressively.
    max_len = 90
    if len(d) > max_len:
        d = d[: max_len - 3].rstrip() + "..."

    return d


def _is_noise_line(line: str) -> bool:
    if not line:
        return True

    n = _strip_accents(line).lower()

    # Common header/footer noise in statements.
    noise_markers = [
        "banco bradesco",
        "bradesco celular",
        "bradesco",
        # Keep "extrato" permissive: it appears in headers and also inside "Extrato inexistente".
        "pagina",
        "página",
        "ouvidoria",
        "sac",
    ]
    if any(m in n for m in noise_markers) and not _DATE_DDMM_RE.match(line):
        # If the line starts with a date, it's likely a transaction, not noise.
        return True

    # Table headers
    if re.search(r"(?i)\bdata\b", line) and re.search(r"(?i)\bsaldo\b", line):
        return True

    # Footer/header lines commonly appended by extraction.
    if re.match(r"(?i)^nome\s*:", line):
        return True
    if re.match(r"(?i)^data\s*:", line):
        return True
    if re.search(r"(?i)\bfolha\s*:\s*\d+\s*/\s*\d+", line):
        return True
    if re.match(r"(?i)^total\b", line):
        return True
    if re.match(r"(?i)^extrato\s+inexistente\b", line):
        return True

    return False


def _is_continuation_marker(line: str) -> bool:
    if not line:
        return False
    return bool(re.match(r"(?i)^(des|rem|dest)\s*:\s*", line.strip()))


def _looks_like_doc_values_line(line: str) -> bool:
    if not line:
        return False
    s = line.strip()
    if not re.match(r"^\d{5,}\b", s):
        return False
    return bool(_MONEY_RE.search(s))


def _looks_like_new_history_header(line: str) -> bool:
    if not line:
        return False
    s = line.strip()
    if _is_continuation_marker(s):
        return False
    if _looks_like_doc_values_line(s):
        return False
    if _MONEY_RE.search(s):
        # If the line has values, treat it as values/continuation; not a header-only history.
        return False
    # Needs at least one letter to be a history label.
    return bool(re.search(r"[A-Za-zÀ-ÿ]", s))


def _parse_line_date(line: str, default_year: int) -> tuple[date | None, int]:
    if not line:
        return None, default_year

    m_full = _DATE_DDMMYYYY_RE.match(line)
    if m_full:
        dd, mm, yyyy = int(m_full.group("dd")), int(m_full.group("mm")), int(m_full.group("yyyy"))
        try:
            return date(yyyy, mm, dd), yyyy
        except ValueError:
            return None, default_year

    m_short = _DATE_DDMM_RE.match(line)
    if m_short:
        dd, mm = int(m_short.group("dd")), int(m_short.group("mm"))
        try:
            return date(default_year, mm, dd), default_year
        except ValueError:
            return None, default_year

    return None, default_year


def parse_bradesco_bank_statement(raw_text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    debug: dict[str, Any] = {}
    warnings: list[str] = []

    if not looks_like_bradesco_bank_statement(raw_text):
        return ({"bank": "BRADESCO", "transactions": [], "reason": "UNSUPPORTED_LAYOUT"}, ["not_bradesco"], debug)

    text = normalize_text(raw_text)
    flat = _flat(text)

    period_start: date | None = None
    period_end: date | None = None
    m = _MOVIMENTACAO_ENTRE_RE.search(flat)
    if m:
        period_start = _parse_date_ddmmyyyy(m.group(1))
        period_end = _parse_date_ddmmyyyy(m.group(2))
    else:
        m = _PERIOD_RE.search(flat)
        if m:
            period_start = _parse_date_ddmmyyyy(m.group(1))
            period_end = _parse_date_ddmmyyyy(m.group(2))

    statement_date = period_end or date.today()
    default_year = statement_date.year

    opening = _extract_money(text, _OPENING_RE)
    closing = _extract_money(text, _CLOSING_RE)

    tx_candidates: list[tuple[date, str, Decimal | None, Decimal | None, bool]] = []
    # tuple: (date, desc, amount_abs, balance, is_balance_row)

    last_date: date | None = None
    pending_prefix: list[str] = []

    for line in (ln.strip() for ln in text.split("\n")):
        if not line:
            continue

        if _is_noise_line(line):
            continue

        tx_date, maybe_year = _parse_line_date(line, default_year)
        if tx_date is None:
            # No date on this line. This can mean:
            # - a new history row (same date as previous dated row)
            # - a doc/value row for the last started transaction
            # - a continuation marker (DES:/REM:/DEST:)
            # - a harmless description continuation

            if _looks_like_new_history_header(line):
                if last_date is None:
                    pending_prefix.append(line)
                else:
                    tx_candidates.append((last_date, line, None, None, False))
                continue

            if tx_candidates:
                prev = tx_candidates[-1]
                amount_abs, balance = prev[2], prev[3]

                # If the current candidate doesn't have values yet, try to fill them from this line.
                if amount_abs is None and _MONEY_RE.search(line):
                    money_matches = list(_MONEY_RE.finditer(line))
                    if money_matches:
                        if len(money_matches) >= 2:
                            bal_m = money_matches[-1]
                            amt_m = money_matches[-2]
                            balance = _parse_brl_money(bal_m.group(0))
                            parsed_amt = _parse_brl_money(amt_m.group(0))
                            amount_abs = abs(parsed_amt) if parsed_amt is not None else None
                        else:
                            amt_m = money_matches[-1]
                            parsed_amt = _parse_brl_money(amt_m.group(0))
                            amount_abs = abs(parsed_amt) if parsed_amt is not None else None

                new_desc = (prev[1] + " " + line).strip() if prev[1] else line
                tx_candidates[-1] = (
                    prev[0],
                    new_desc,
                    amount_abs,
                    balance,
                    prev[4],
                )
            continue

        last_date = tx_date

        default_year = maybe_year

        money_matches = list(_MONEY_RE.finditer(line))
        prefix = " ".join(pending_prefix).strip()
        pending_prefix = []

        if not money_matches:
            # Date without money: create a candidate and let continuation lines fill values.
            desc_start = (
                _DATE_DDMMYYYY_RE.match(line).end() if _DATE_DDMMYYYY_RE.match(line) else _DATE_DDMM_RE.match(line).end()
            )
            desc = _clean_description(line[desc_start:])
            if prefix:
                desc = _clean_description(prefix + " " + desc)
            tx_candidates.append((tx_date, desc, None, None, False))
            continue

        # Heuristic: if we have at least 2 money tokens, last is balance, previous is amount.
        amount_abs: Decimal | None
        balance: Decimal | None

        if len(money_matches) >= 2:
            bal_m = money_matches[-1]
            amt_m = money_matches[-2]
            balance = _parse_brl_money(bal_m.group(0))
            amount_abs = _parse_brl_money(amt_m.group(0))
            if amount_abs is not None:
                amount_abs = abs(amount_abs)
            desc_raw = line[: amt_m.start()].strip()
        else:
            # Only one number: treat as amount, balance unknown
            amt_m = money_matches[-1]
            balance = None
            amount_abs = _parse_brl_money(amt_m.group(0))
            if amount_abs is not None:
                amount_abs = abs(amount_abs)
            desc_raw = line[: amt_m.start()].strip()

        # Remove the leading date token from description
        m_full = _DATE_DDMMYYYY_RE.match(desc_raw)
        m_short = _DATE_DDMM_RE.match(desc_raw)
        if m_full:
            desc_raw = desc_raw[m_full.end() :].strip()
        elif m_short:
            desc_raw = desc_raw[m_short.end() :].strip()

        desc = _clean_description(desc_raw)
        if prefix:
            desc = _clean_description(prefix + " " + desc)

        is_balance_row = bool(re.search(r"(?i)\bsaldo\b", desc))
        if is_balance_row and opening is None and balance is not None and re.search(r"(?i)anterior|inicial", desc):
            opening = balance
        if is_balance_row and closing is None and balance is not None and re.search(r"(?i)final|atual", desc):
            closing = balance

        tx_candidates.append((tx_date, desc, amount_abs, balance, is_balance_row))

    # If we have dd/mm without year and period gives us a hint, correct obvious year rollover.
    if period_start and period_end and period_start.year != period_end.year:
        fixed: list[tuple[date, str, Decimal | None, Decimal | None, bool]] = []
        for tx_date, desc, amount_abs, balance, is_balance_row in tx_candidates:
            if tx_date.year == period_end.year and tx_date.month == 12 and period_end.month == 1:
                # very unlikely case; ignore
                fixed.append((tx_date, desc, amount_abs, balance, is_balance_row))
                continue
            if tx_date.year == period_end.year and period_start.month == 12 and tx_date.month == 12:
                fixed.append((tx_date.replace(year=period_start.year), desc, amount_abs, balance, is_balance_row))
                continue
            fixed.append((tx_date, desc, amount_abs, balance, is_balance_row))
        tx_candidates = fixed

    # Establish opening balance if missing but we have first balance and amount.
    if opening is None:
        first = next((t for t in tx_candidates if t[2] is not None and t[3] is not None and not t[4]), None)
        if first is not None:
            # Guess sign using keywords; fallback to DEBIT.
            desc = _strip_accents(first[1]).lower()
            credit_kw = ["receb", "deposit", "credito", "salario", "pix receb"]
            debit_kw = ["pag", "compra", "tarifa", "saque", "envio", "debito", "pix envi"]
            is_credit = any(k in desc for k in credit_kw) and not any(k in desc for k in debit_kw)
            if is_credit:
                opening = first[3] - (first[2] or Decimal("0.00"))
            else:
                opening = first[3] + (first[2] or Decimal("0.00"))
            debug["openingDerivedFromFirstTx"] = {"date": first[0].isoformat(), "assumed": "CREDIT" if is_credit else "DEBIT"}

    if opening is None:
        opening = Decimal("0.00")

    parsed: list[_ParsedTx] = []
    running = opening

    for tx_date, desc, amount_abs, balance, is_balance_row in tx_candidates:
        if is_balance_row:
            if balance is not None:
                running = balance
            parsed.append(_ParsedTx(tx_date, desc or "Saldo", Decimal("0.00"), balance, "BALANCE"))
            continue

        if amount_abs is None:
            # Skip rows without a parsable amount.
            continue

        tx_type = "DEBIT"
        signed_amount = -amount_abs

        if balance is not None:
            # Choose the sign that best matches the observed balance.
            if (running + amount_abs).quantize(Decimal("0.01")) == balance.quantize(Decimal("0.01")):
                tx_type = "CREDIT"
                signed_amount = amount_abs
            elif (running - amount_abs).quantize(Decimal("0.01")) == balance.quantize(Decimal("0.01")):
                tx_type = "DEBIT"
                signed_amount = -amount_abs
            else:
                # Fallback: sign by delta
                delta = (balance - running).quantize(Decimal("0.01"))
                if abs(delta) == amount_abs.quantize(Decimal("0.01")) and delta > 0:
                    tx_type = "CREDIT"
                    signed_amount = amount_abs
                elif abs(delta) == amount_abs.quantize(Decimal("0.01")) and delta < 0:
                    tx_type = "DEBIT"
                    signed_amount = -amount_abs

            running = balance
        else:
            running = (running + signed_amount).quantize(Decimal("0.01"))

        parsed.append(_ParsedTx(tx_date, desc, signed_amount, balance, tx_type))

    if closing is None:
        last_balance = next((t.balance for t in reversed(parsed) if t.balance is not None), None)
        closing = last_balance if last_balance is not None else running

    debug.update(
        {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "statementDate": statement_date.isoformat() if statement_date else None,
            "txCount": len(parsed),
        }
    )

    result: dict[str, Any] = {
        "bank": "BRADESCO",
        "statementDate": statement_date.isoformat(),
        "openingBalance": float(opening.quantize(Decimal("0.01"))),
        "closingBalance": float(closing.quantize(Decimal("0.01"))),
        "transactions": [
            {
                "transactionDate": t.transactionDate.isoformat(),
                "description": _summarize_description(t.description),
                "amount": float((t.amountAbs or Decimal("0.00")).quantize(Decimal("0.01"))),
                "balance": float(t.balance.quantize(Decimal("0.01"))) if t.balance is not None else None,
                "type": t.type,
            }
            for t in parsed
        ],
    }

    if not result["transactions"]:
        result["reason"] = "UNSUPPORTED_LAYOUT"

    return result, warnings, debug
