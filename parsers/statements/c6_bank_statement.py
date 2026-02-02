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

    # Normalize common unicode minus variants
    s = s.replace("−", "-").replace("–", "-").replace("—", "-")

    sign = -1 if s.lstrip().startswith("-") else 1

    # Keep digits and separators
    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")

    try:
        d = Decimal(s)
    except InvalidOperation:
        return None

    return d * sign


_OPENING_RE = re.compile(
    r"(?i)\b(saldo\s*(?:anterior|inicial))\b[^0-9\-]*(-?\d{1,3}(?:\.\d{3})*,\d{2})"
)
_CLOSING_RE = re.compile(
    r"(?i)\b(saldo\s*(?:final|atual))\b[^0-9\-]*(-?\d{1,3}(?:\.\d{3})*,\d{2})"
)


def _extract_money(text: str, pattern: re.Pattern[str]) -> Decimal | None:
    n = _flat(text)
    m = pattern.search(n)
    if not m:
        return None
    return _parse_brl_money(m.group(2))


def looks_like_c6_bank_statement(text: str) -> bool:
    n = _strip_accents(_flat(text)).lower()
    if not n:
        return False

    # Not super strict; PDFs vary between "C6 BANK" and legal entity names.
    markers = [
        "c6 bank",
        "banco c6",
        "banco c6 s.a",
        "c6 s.a",
        "c6 conta",
        "extrato",
    ]
    score = 0
    for mk in markers:
        if mk in n:
            score += 1

    # Require both a C6 marker and statement-like content.
    has_c6 = ("c6 bank" in n) or ("banco c6" in n)
    has_table_ish = ("saldo" in n) or ("periodo" in n) or ("período" in _flat(text).lower())
    return has_c6 and has_table_ish and score >= 2


@dataclass(frozen=True)
class ParsedTx:
    transactionDate: date
    description: str
    amount: Decimal
    balance: Decimal | None
    type: str  # DEBIT | CREDIT | BALANCE


def _is_balance_line(description: str) -> bool:
    d = _strip_accents((description or "")).lower().strip()
    if not d:
        return False

    return (
        d.startswith("saldo")
        or "saldo do dia" in d
        or "saldo anterior" in d
        or "saldo inicial" in d
        or "saldo final" in d
        or "saldo atual" in d
    )


def _clean_description_and_infer_dc_from_currency_marker(description: str) -> tuple[str, str | None]:
    """C6 sometimes prints a currency marker right before the amount.

    Examples seen in extracted text:
    - "... -R$ 59,00 941,00"  -> description ends with "-R$" (debit)
    - "... R$ 6.500,00 7.441,00" -> description ends with "R$" (credit)

    Our regexes capture that token as part of the description, so we:
    1) remove the trailing marker from description
    2) infer D/C when explicit D/C column is absent
    """

    d = re.sub(r"\s+", " ", (description or "")).strip()
    if not d:
        return "", None

    # Normalize common unicode minus variants
    d = d.replace("−", "-").replace("–", "-").replace("—", "-")

    m = re.search(r"(?i)(?:^|\s)(-\s*R\$|R\$)\s*$", d)
    if not m:
        return d, None

    token = (m.group(1) or "").replace(" ", "")
    cleaned = d[: m.start()].strip()

    if token.startswith("-"):
        return cleaned, "D"
    return cleaned, "C"


# Typical table-ish line:
#  dd/mm  <desc...>  <amount>  <balance>
#  dd/mm  <desc...>  <amount>
_TX_WITH_BALANCE_RE = re.compile(
    r"^\s*(\d{2})/(\d{2})(?:/(\d{4}))?\s+(.+?)\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})(?:\s*([DC]))?\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*$",
    re.IGNORECASE,
)
_BALANCE_ONLY_RE = re.compile(
    r"^\s*(\d{2})/(\d{2})(?:/(\d{4}))?\s+(.+?)\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*$",
    re.IGNORECASE,
)
_TX_NO_BALANCE_RE = re.compile(
    r"^\s*(\d{2})/(\d{2})(?:/(\d{4}))?\s+(.+?)\s+(-?\d{1,3}(?:\.\d{3})*,\d{2})(?:\s*([DC]))?\s*$",
    re.IGNORECASE,
)


def _infer_year(
    dd: int,
    mm: int,
    yyyy: int | None,
    period_start: date | None,
    period_end: date | None,
) -> date | None:
    if yyyy is not None:
        try:
            return date(yyyy, mm, dd)
        except ValueError:
            return None

    # Infer based on statement period if we have it.
    if period_end is not None and period_start is not None:
        # If statement spans a year boundary (e.g. Dec->Jan) and month is "after" end month,
        # then it likely belongs to the start year.
        end_year = period_end.year
        start_year = period_start.year
        if start_year != end_year and mm > period_end.month:
            year = start_year
        else:
            year = end_year

        try:
            return date(year, mm, dd)
        except ValueError:
            return None

    # Fallback: use current year
    try:
        return date(date.today().year, mm, dd)
    except ValueError:
        return None


def parse_c6_bank_statement(raw_text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Parse a C6 Bank account statement from extracted PDF text.

    Returns (result, warnings, debug).
    """

    warnings: list[str] = []
    debug: dict[str, Any] = {}

    normalized = normalize_text(raw_text)
    flat = _flat(raw_text)

    if not looks_like_c6_bank_statement(raw_text):
        return ({"bank": "C6", "transactions": [], "reason": "UNSUPPORTED_LAYOUT"}, ["not_c6"], debug)

    period_start: date | None = None
    period_end: date | None = None
    m_period = _PERIOD_RE.search(flat)
    if m_period:
        period_start = _parse_date_ddmmyyyy(m_period.group(1))
        period_end = _parse_date_ddmmyyyy(m_period.group(2))

    statement_date = period_end
    if statement_date is None:
        # Fallback: use the last explicit dd/mm/yyyy in the document
        all_dates = re.findall(r"\b\d{2}/\d{2}/\d{4}\b", flat)
        if all_dates:
            statement_date = _parse_date_ddmmyyyy(all_dates[-1])

    opening = _extract_money(raw_text, _OPENING_RE)
    closing = _extract_money(raw_text, _CLOSING_RE)

    txs: list[ParsedTx] = []

    # Track the last explicit "Saldo do dia" encountered in the document.
    # If present for the last transaction date, it should define the closing balance.
    last_saldo_do_dia_date: date | None = None
    last_saldo_do_dia_value: Decimal | None = None

    for ln in normalized.split("\n"):
        line = (ln or "").strip()
        if not line:
            continue

        # Skip obvious headers
        low = _strip_accents(line).lower()
        if low in {"data", "descricao", "descrição", "valor", "saldo"}:
            continue
        if "data descricao" in low and ("valor" in low or "saldo" in low):
            continue

        # Some C6 exports show balance rows as: "Saldo do dia 21/01/26 R$ 1.484,06"
        # (i.e., the date is part of the description and the row does not start with dd/mm).
        if "saldo do dia" in low:
            m_day = re.search(r"(?i)saldo\s+do\s+dia\s+(\d{2})/(\d{2})/(\d{2}|\d{4})", line)
            if m_day:
                dd, mm = int(m_day.group(1)), int(m_day.group(2))
                yyyy_raw = m_day.group(3)
                yyyy = int(yyyy_raw)
                if len(yyyy_raw) == 2:
                    yyyy += 2000

                try:
                    tx_date = date(yyyy, mm, dd)
                except ValueError:
                    tx_date = None

                if tx_date is not None:
                    # Take the last BRL-like number as the balance value.
                    values = re.findall(r"-?\d{1,3}(?:\.\d{3})*,\d{2}", line)
                    if values:
                        value = _parse_brl_money(values[-1])
                        if value is not None:
                            txs.append(
                                ParsedTx(
                                    transactionDate=tx_date,
                                    description="Saldo do dia",
                                    amount=Decimal("0.00"),
                                    balance=value,
                                    type="BALANCE",
                                )
                            )
                            last_saldo_do_dia_date = tx_date
                            last_saldo_do_dia_value = value
                            continue

        m = _TX_WITH_BALANCE_RE.match(line)
        if m:
            dd, mm = int(m.group(1)), int(m.group(2))
            yyyy = int(m.group(3)) if m.group(3) else None
            description = re.sub(r"\s+", " ", (m.group(4) or "")).strip()
            amount = _parse_brl_money(m.group(5) or "")
            dc = (m.group(6) or "").strip().upper() if m.group(6) else None
            balance = _parse_brl_money(m.group(7) or "")

            if amount is None or balance is None:
                continue

            tx_date = _infer_year(dd, mm, yyyy, period_start, period_end)
            if tx_date is None:
                continue

            # C6 can emit "-R$" / "R$" as a trailing token in the description.
            description, inferred_dc = _clean_description_and_infer_dc_from_currency_marker(description)
            if dc is None and inferred_dc is not None:
                dc = inferred_dc

            if _is_balance_line(description):
                txs.append(
                    ParsedTx(
                        transactionDate=tx_date,
                        description=description,
                        amount=Decimal("0.00"),
                        balance=balance,
                        type="BALANCE",
                    )
                )
                if balance is not None:
                    last_saldo_do_dia_date = tx_date
                    last_saldo_do_dia_value = balance
                continue

            # Type inference
            if dc == "C":
                tx_type = "CREDIT"
            elif dc == "D":
                tx_type = "DEBIT"
            else:
                tx_type = "CREDIT" if amount >= 0 else "DEBIT"

            # Normalize signed amount like Java side: DEBIT negative, CREDIT positive
            if tx_type == "DEBIT" and amount > 0:
                amount = -amount
            if tx_type == "CREDIT" and amount < 0:
                amount = abs(amount)

            txs.append(
                ParsedTx(
                    transactionDate=tx_date,
                    description=description,
                    amount=amount,
                    balance=balance,
                    type=tx_type,
                )
            )
            continue

        # Balance-only rows like "Saldo do dia 1.100,00".
        # Must come AFTER TX_WITH_BALANCE; otherwise it would swallow real transactions.
        m = _BALANCE_ONLY_RE.match(line)
        if m:
            dd, mm = int(m.group(1)), int(m.group(2))
            yyyy = int(m.group(3)) if m.group(3) else None
            description = re.sub(r"\s+", " ", (m.group(4) or "")).strip()
            value = _parse_brl_money(m.group(5) or "")
            if value is None:
                continue

            tx_date = _infer_year(dd, mm, yyyy, period_start, period_end)
            if tx_date is None:
                continue

            if _is_balance_line(description):
                txs.append(
                    ParsedTx(
                        transactionDate=tx_date,
                        description=description,
                        amount=Decimal("0.00"),
                        balance=value,
                        type="BALANCE",
                    )
                )
                last_saldo_do_dia_date = tx_date
                last_saldo_do_dia_value = value
                continue

            # If it's not a balance-ish description, don't swallow it; let TX_NO_BALANCE try.

        m = _TX_NO_BALANCE_RE.match(line)
        if m:
            dd, mm = int(m.group(1)), int(m.group(2))
            yyyy = int(m.group(3)) if m.group(3) else None
            description = re.sub(r"\s+", " ", (m.group(4) or "")).strip()
            amount = _parse_brl_money(m.group(5) or "")
            dc = (m.group(6) or "").strip().upper() if m.group(6) else None

            if amount is None:
                continue

            tx_date = _infer_year(dd, mm, yyyy, period_start, period_end)
            if tx_date is None:
                continue

            description, inferred_dc = _clean_description_and_infer_dc_from_currency_marker(description)
            if dc is None and inferred_dc is not None:
                dc = inferred_dc

            if _is_balance_line(description):
                txs.append(
                    ParsedTx(
                        transactionDate=tx_date,
                        description=description,
                        amount=Decimal("0.00"),
                        balance=None,
                        type="BALANCE",
                    )
                )
                continue

            if dc == "C":
                tx_type = "CREDIT"
            elif dc == "D":
                tx_type = "DEBIT"
            else:
                tx_type = "CREDIT" if amount >= 0 else "DEBIT"

            if tx_type == "DEBIT" and amount > 0:
                amount = -amount
            if tx_type == "CREDIT" and amount < 0:
                amount = abs(amount)

            txs.append(
                ParsedTx(
                    transactionDate=tx_date,
                    description=description,
                    amount=amount,
                    balance=None,
                    type=tx_type,
                )
            )

    txs.sort(key=lambda t: (t.transactionDate, t.description))

    # Prefer the last explicit "Saldo do dia" for the last date in the document.
    if txs and last_saldo_do_dia_date is not None and last_saldo_do_dia_value is not None:
        max_date = max(t.transactionDate for t in txs)
        if last_saldo_do_dia_date == max_date:
            closing = last_saldo_do_dia_value

    # Infer statement date from last transaction if needed
    if statement_date is None and txs:
        statement_date = txs[-1].transactionDate

    if statement_date is None:
        statement_date = date.today()
        warnings.append("statement_date_fallback_today")

    # Infer opening/closing similar to Java behavior
    if opening is None and txs:
        first = next((t for t in txs if t.type != "BALANCE" and t.balance is not None), None)
        if first and first.balance is not None:
            opening = first.balance - first.amount

    # If we still don't have an opening balance, but we do have an explicit
    # "Saldo do dia" for the first date in the document, derive opening from it.
    # The saldo do dia usually represents the end-of-day balance.
    if opening is None and txs:
        first_balance = next((t for t in txs if t.type == "BALANCE" and t.balance is not None), None)
        if first_balance is not None and first_balance.balance is not None:
            day = first_balance.transactionDate
            day_net = sum(
                (t.amount for t in txs if t.type != "BALANCE" and t.transactionDate == day),
                start=Decimal("0.00"),
            )
            opening = first_balance.balance - day_net
            debug["openingDerivedFromSaldoDoDia"] = {
                "date": day.isoformat(),
                "saldoDoDia": float(first_balance.balance.quantize(Decimal("0.01"))),
                "dayNet": float(day_net.quantize(Decimal("0.01"))),
            }

    if opening is None:
        opening = Decimal("0.00")

    # Fill running balances when missing
    any_missing_balance = any(t.type != "BALANCE" and t.balance is None for t in txs)
    if any_missing_balance:
        running = opening
        fixed: list[ParsedTx] = []
        for t in txs:
            if t.type == "BALANCE":
                fixed.append(t)
                # Balance rows define the running balance when they carry a value.
                if t.balance is not None:
                    running = t.balance
                continue
            next_balance = t.balance if t.balance is not None else running + t.amount
            fixed.append(
                ParsedTx(
                    transactionDate=t.transactionDate,
                    description=t.description,
                    amount=t.amount,
                    balance=next_balance,
                    type=t.type,
                )
            )
            running = next_balance
        txs = fixed
        if closing is None:
            closing = running

    if closing is None and txs:
        last_with_balance = next((t for t in reversed(txs) if t.balance is not None), None)
        if last_with_balance and last_with_balance.balance is not None:
            closing = last_with_balance.balance

    if closing is None:
        closing = Decimal("0.00")

    debug.update(
        {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "statementDate": statement_date.isoformat() if statement_date else None,
            "txCount": len(txs),
        }
    )

    result: dict[str, Any] = {
        "bank": "C6",
        "statementDate": statement_date.isoformat(),
        "openingBalance": float(opening.quantize(Decimal("0.01"))),
        "closingBalance": float(closing.quantize(Decimal("0.01"))),
        "transactions": [
            {
                "transactionDate": t.transactionDate.isoformat(),
                "description": t.description,
                "amount": float(t.amount.quantize(Decimal("0.01"))),
                "balance": float(t.balance.quantize(Decimal("0.01"))) if t.balance is not None else None,
                "type": t.type,
            }
            for t in txs
        ],
    }

    if not result["transactions"]:
        result["reason"] = "UNSUPPORTED_LAYOUT"

    return result, warnings, debug
