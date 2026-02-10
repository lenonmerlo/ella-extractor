from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")

# "período de visualização: 04/10/2025 até 03/12/2025"
_PERIOD_RE = re.compile(
    r"(?i)per[ií]odo\s+de\s+visualiza[cç][aã]o\s*:\s*(\d{2})/(\d{2})/(\d{4})\s*(?:at[eé]|a|\-|\u00e0)\s*(\d{2})/(\d{2})/(\d{4})"
)

# "emitido em: 03/12/2025 12:47:47"
_EMIT_RE = re.compile(r"(?i)emitido\s+em\s*:\s*(\d{2})/(\d{2})/(\d{4})\b")

_DATE_AT_START_RE = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4})\b")

# BRL number (optionally signed, thousands dot, decimal comma)
_MONEY_RE = re.compile(r"(?:(?P<sign>[+\-\u2212])\s*)?(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})\b")


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

    # Collapse repeated spaces/tabs but keep line breaks
    text = re.sub(r"[ \t]{2,}", " ", text)

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


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def looks_like_itau_bank_statement(text: str) -> bool:
    n = _strip_accents(normalize_text(text)).lower()
    if not n:
        return False

    # Common markers in Itaú checking account statements
    if "extrato conta" in n and "lancamentos" in n:
        return True
    if "periodo de visualizacao" in n and "saldo do dia" in n:
        return True
    if "data lancamentos" in n and "saldo" in n and "valor" in n:
        return True

    return False


def _parse_date(dd: str, mm: str, yyyy: str) -> date | None:
    try:
        return date(int(yyyy), int(mm), int(dd))
    except Exception:
        return None


def _parse_brl_money(value: str) -> Decimal | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    s = s.replace("\u2212", "-").replace("–", "-").replace("—", "-")

    sign = -1 if s.lstrip().startswith("-") else 1

    # Keep only digits and separators
    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")

    try:
        d = Decimal(s)
    except InvalidOperation:
        return None

    return d * sign


def _last_money_at_end(line: str) -> tuple[Decimal | None, int | None]:
    """Returns (value, start_index) for the last money token if it ends the line."""

    if not line:
        return None, None

    stripped = line.rstrip()
    matches = list(_MONEY_RE.finditer(stripped))
    if not matches:
        return None, None

    m = matches[-1]
    if m.end() != len(stripped):
        return None, None

    raw_val = m.group("val")
    sign = m.group("sign")
    prefix = "-" if sign in {"-", "\u2212"} else ""
    d = _parse_brl_money(prefix + raw_val)
    return d, m.start()


def _is_noise_line(line: str) -> bool:
    if not line:
        return True

    low = _strip_accents(line).lower().strip()
    if not low:
        return True

    # Table header line
    if low.startswith("data ") and "lancamentos" in low and "valor" in low:
        return True

    # Static headers and boilerplate
    if "consultas" in low and "ouvidoria" in low:
        return True
    if low.startswith("aviso"):
        return True
    if low.startswith("os saldos acima"):
        return True
    if "itau.com.br" in low:
        return True

    return False


def _clean_description(desc: str) -> str:
    if not desc:
        return ""

    # Fix glued dd/mm inside description: "Raimund03/12" -> "Raimund 03/12"
    desc = re.sub(r"([A-Za-zÀ-ÿ])(\d{2}/\d{2})\b", r"\1 \2", desc)
    desc = re.sub(r"\s{2,}", " ", desc).strip()

    # Remove repeated whitespace and trailing separators
    desc = desc.strip(" -\t")
    return desc


@dataclass
class Tx:
    transactionDate: date
    description: str
    amountAbs: Decimal | None
    balance: Decimal | None
    type: str  # CREDIT|DEBIT|BALANCE


def parse_itau_bank_statement(text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    warnings: list[str] = []
    debug: dict[str, Any] = {}

    normalized = normalize_text(text)
    flat = re.sub(r"\s+", " ", normalized)

    period_start: date | None = None
    period_end: date | None = None
    m = _PERIOD_RE.search(flat)
    if m:
        period_start = _parse_date(m.group(1), m.group(2), m.group(3))
        period_end = _parse_date(m.group(4), m.group(5), m.group(6))

    emit_date: date | None = None
    m2 = _EMIT_RE.search(flat)
    if m2:
        emit_date = _parse_date(m2.group(1), m2.group(2), m2.group(3))

    statement_date = emit_date or period_end
    if statement_date is None:
        warnings.append("missing_statement_date")

    # Parse rows
    txs: list[Tx] = []
    balances_by_date: dict[date, Decimal] = {}

    current_tx: Tx | None = None

    for raw_line in normalized.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if _is_noise_line(line):
            # Stop early on boilerplate blocks
            if _strip_accents(line).lower().startswith("aviso"):
                break
            continue

        date_m = _DATE_AT_START_RE.match(line)
        if date_m:
            tx_date = _parse_date(date_m.group(1), date_m.group(2), date_m.group(3))
            if not tx_date:
                continue

            rest = line[date_m.end() :].strip()

            # Itaú bank statement has daily balance rows
            if _strip_accents(rest).upper().startswith("SALDO DO DIA"):
                bal_val, _idx = _last_money_at_end(rest)
                if bal_val is None:
                    warnings.append("unparsed_balance_row")
                    continue

                balances_by_date[tx_date] = bal_val
                txs.append(
                    Tx(
                        transactionDate=tx_date,
                        description="SALDO DO DIA",
                        amountAbs=Decimal("0.00"),
                        balance=bal_val,
                        type="BALANCE",
                    )
                )
                current_tx = None
                continue

            amount_val, amount_idx = _last_money_at_end(rest)
            if amount_val is None or amount_idx is None:
                # If a date line doesn't end with a value, it might be a wrapped line.
                # Treat it as a new transaction header anyway.
                current_tx = Tx(
                    transactionDate=tx_date,
                    description=_clean_description(rest),
                    amountAbs=None,
                    balance=None,
                    type="DEBIT",
                )
                txs.append(current_tx)
                warnings.append("missing_amount_on_tx_line")
                continue

            desc = rest[:amount_idx].strip()
            desc = _clean_description(desc)

            tx_type = "CREDIT" if amount_val > 0 else "DEBIT"
            amount_abs = abs(amount_val)

            current_tx = Tx(
                transactionDate=tx_date,
                description=desc,
                amountAbs=amount_abs,
                balance=None,
                type=tx_type,
            )
            txs.append(current_tx)
            continue

        # Continuation line: append to previous tx description if it looks meaningful.
        if current_tx is not None:
            if _is_noise_line(line):
                continue
            # Avoid appending headers that show up mid-page
            low = _strip_accents(line).lower()
            if low.startswith("periodo de visualizacao") or "extrato conta" in low:
                continue

            current_tx.description = _clean_description(current_tx.description + " " + line)

    # Opening/closing balances from daily balance rows
    opening: Decimal | None = None
    closing: Decimal | None = None

    if balances_by_date:
        dates_sorted = sorted(balances_by_date.keys())
        opening = balances_by_date[dates_sorted[0]]
        closing = balances_by_date[dates_sorted[-1]]
    else:
        warnings.append("missing_daily_balances")

    debug.update(
        {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "emitDate": emit_date.isoformat() if emit_date else None,
            "statementDate": statement_date.isoformat() if statement_date else None,
            "txCount": len(txs),
            "balanceDays": len(balances_by_date),
        }
    )

    result: dict[str, Any] = {
        "bank": "ITAU",
        "statementDate": statement_date.isoformat() if statement_date else None,
        "openingBalance": float((opening or Decimal("0.00")).quantize(Decimal("0.01"))),
        "closingBalance": float((closing or Decimal("0.00")).quantize(Decimal("0.01"))),
        "transactions": [
            {
                "transactionDate": t.transactionDate.isoformat(),
                "description": t.description,
                "amount": float((t.amountAbs or Decimal("0.00")).quantize(Decimal("0.01"))),
                "balance": float(t.balance.quantize(Decimal("0.01"))) if t.balance is not None else None,
                "type": t.type,
            }
            for t in txs
        ],
    }

    if not result["transactions"] or not statement_date:
        result["reason"] = "UNSUPPORTED_LAYOUT"

    return result, warnings, debug
