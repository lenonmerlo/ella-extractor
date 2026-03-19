from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")
_FULL_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_PERIOD_RE = re.compile(
    r"(?i)\bper[ií]odo\b[^0-9]*(\d{2}/\d{2}/\d{4})\s*(?:a|\-|at[eé])\s*(\d{2}/\d{2}/\d{4})"
)
_DATE_PREFIX_RE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})\b")
_DAY_PREFIX_RE = re.compile(r"^(\d{2})\b")
_TRAILING_MONEY_RE = re.compile(
    r"(?:(?P<sign>[+\-−])\s*)?(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})(?:\s*(?:(?P<dc>[DC])|\((?P<pm>[+\-−])\)))?\s*$",
    re.IGNORECASE,
)
_MONEY_TOKEN_RE = re.compile(
    r"(?:(?P<currency>R\$)\s*)?(?:(?P<sign>[+\-−])\s*)?"
    r"(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})(?:\s*(?:(?P<dc>[DC])|\((?P<pm>[+\-−])\)))?",
    re.IGNORECASE,
)

_TABLE_END_MARKERS = (
    "informacoes adicionais",
    "informações adicionais",
    "informacoes complementares",
    "informações complementares",
    "total aplicacoes financeiras",
    "total aplicações financeiras",
)

_TRANSACTION_HEADER_RE = re.compile(r"(?i)\bdia\b.*\bhistoric[oo]\b.*\bvalor\b")

_NOISE_MARKERS = (
    "central de relacionamento",
    "ouvidoria",
    "sac",
    "sisbb",
    "agencia",
    "agência",
    "taxa limite especial",
    "limite especial da conta",
    "tributos (iof)",
    "total aplicacoes financeiras",
    "total aplicações financeiras",
    "saldos por dia",
    "base sujeitos a confirmacao",
    "base sujeitos a confirmação",
)


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)
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


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def _strip_accents(s: str) -> str:
    if not s:
        return ""
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _parse_date_ddmmyyyy(value: str) -> date | None:
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (value or "").strip())
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


def looks_like_banco_do_brasil_bank_statement(text: str) -> bool:
    n = _strip_accents(_flat(text)).lower()
    if not n:
        return False
    if "banco do brasil" not in n and "bb" not in n:
        return False
    markers = ["extrato", "saldo do dia", "historico", "documento", "lote"]
    return any(marker in n for marker in markers)


def _is_noise_line(line: str) -> bool:
    n = _strip_accents(line).lower().strip()
    if not n:
        return True

    if n.startswith("dia") and "historico" in n and "valor" in n:
        return True
    if n.startswith("lancamentos") or n.startswith("lançamentos"):
        return True
    if "central de relacionamento" in n or "ouvidoria" in n:
        return True
    if "sisbb" in n:
        return True
    if n.startswith("agencia") or n.startswith("agência"):
        return True
    if n.startswith("conta"):
        return True
    if n.startswith("cliente"):
        return True

    if any(marker in n for marker in _NOISE_MARKERS):
        return True

    return False


def _is_table_end_line(line: str) -> bool:
    n = _strip_accents((line or "").lower()).strip()
    return any(marker in n for marker in _TABLE_END_MARKERS)


def _is_continuation_line(line: str) -> bool:
    n = _strip_accents((line or "").lower()).strip()
    if not n:
        return False
    if _is_table_end_line(n):
        return False
    if _TRANSACTION_HEADER_RE.search(n):
        return False
    if any(marker in n for marker in _NOISE_MARKERS):
        return False
    if "%" in n:
        return False
    if "saldo do dia" in n:
        return False
    return True


def _should_drop_transaction(description: str, amount: Decimal) -> bool:
    n = _strip_accents((description or "").lower()).strip()
    if not n:
        return True
    if any(marker in n for marker in _NOISE_MARKERS):
        return True
    if amount == Decimal("0.00") and any(
        marker in n for marker in ("total aplicacoes financeiras", "total aplicações financeiras", "saldos por dia")
    ):
        return True
    return False


def _push_warning(warnings: list[str], item: str, *, max_items: int = 30) -> None:
    if len(warnings) < max_items:
        warnings.append(item)
        return
    if "warnings_truncated" not in warnings:
        warnings.append("warnings_truncated")


def _extract_trailing_amount(line: str) -> tuple[Decimal | None, str | None, int | None]:
    m = _TRAILING_MONEY_RE.search((line or "").strip())
    if not m:
        return None, None, None

    sign = m.group("sign") or ""
    raw = f"{sign}{m.group('val')}"
    amount = _parse_brl_money(raw)
    dc = (m.group("dc") or "").upper() or None
    pm = (m.group("pm") or "").replace("−", "-")
    if dc is None and pm == "+":
        dc = "C"
    if dc is None and pm == "-":
        dc = "D"

    return amount, dc, m.start()


def _extract_primary_amount(line: str) -> tuple[Decimal | None, str | None, int | None]:
    matches = list(_MONEY_TOKEN_RE.finditer((line or "").strip()))
    if not matches:
        return _extract_trailing_amount(line)

    # In layouts with both Valor and Saldo columns, first amount is usually the transaction value.
    chosen = matches[0]

    sign = chosen.group("sign") or ""
    raw = f"{sign}{chosen.group('val')}"
    amount = _parse_brl_money(raw)
    dc = (chosen.group("dc") or "").upper() or None
    pm = (chosen.group("pm") or "").replace("−", "-")
    if dc is None and pm == "+":
        dc = "C"
    if dc is None and pm == "-":
        dc = "D"

    return amount, dc, chosen.start()


def _clean_description(desc: str) -> str:
    d = re.sub(r"\s+", " ", (desc or "").strip())
    d = re.sub(r"^(?:\d+\s+){1,3}", "", d).strip()
    d = re.sub(r"\b\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2}\b", "", d).strip()
    d = re.sub(r"\s+", " ", d)

    max_len = 90
    if len(d) <= max_len:
        return d
    return d[: max_len - 3].rstrip() + "..."


def _infer_signed_amount(amount: Decimal, dc: str | None, description: str) -> tuple[Decimal, str]:
    abs_amount = abs(amount)
    if dc == "D":
        return -abs_amount, "DEBIT"
    if dc == "C":
        return abs_amount, "CREDIT"

    n = _strip_accents(description).lower()
    compact = re.sub(r"\s+", " ", n).strip()
    if compact in {"rende facil", "bb rende facil"}:
        return abs_amount, "CREDIT"
    if any(token in n for token in ("credito", "receb", "deposito", "devolucao", "estorno")):
        return abs_amount, "CREDIT"
    return -abs_amount, "DEBIT"


def _is_balance_description(text: str) -> bool:
    n = _strip_accents((text or "").lower())
    compact = re.sub(r"\s+", " ", n).strip()
    letters_only = re.sub(r"[^a-z]", "", n)
    if compact.startswith("saldo do dia"):
        return True
    if compact.startswith("saldo anterior"):
        return True
    if compact == "saldo":
        return True
    if letters_only.startswith("saldo"):
        return True
    return False


@dataclass(frozen=True)
class _Tx:
    transactionDate: date
    description: str
    amount: Decimal
    balance: Decimal | None
    type: str


def parse_banco_do_brasil_bank_statement(raw_text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    warnings: list[str] = []
    debug: dict[str, Any] = {}

    if not looks_like_banco_do_brasil_bank_statement(raw_text):
        return ({"bank": "BANCO_DO_BRASIL", "transactions": [], "reason": "UNSUPPORTED_LAYOUT"}, ["not_banco_do_brasil"], debug)

    text = normalize_text(raw_text)
    flat = _flat(text)

    period_start: date | None = None
    period_end: date | None = None
    pm = _PERIOD_RE.search(flat)
    if pm:
        period_start = _parse_date_ddmmyyyy(pm.group(1))
        period_end = _parse_date_ddmmyyyy(pm.group(2))

    fallback_year = (period_end or date.today()).year
    fallback_month = (period_end or date.today()).month

    txs: list[_Tx] = []
    balances_by_date: dict[date, Decimal] = {}
    current_date: date | None = None
    last_tx_index: int | None = None

    table_started = False

    for line in (ln.strip() for ln in text.splitlines()):
        if not line:
            continue
        if table_started and _is_table_end_line(line):
            break
        if _TRANSACTION_HEADER_RE.search(_strip_accents(line).lower()):
            table_started = True
            continue
        if _is_noise_line(line):
            if table_started and any(
                marker in _strip_accents(line).lower()
                for marker in ("total aplicacoes financeiras", "total aplicações financeiras")
            ):
                # A strong footer marker means the statement table likely ended.
                break
            continue

        if re.match(r"^\d{2}/\d{2}(?:/\d{2,4})?\s+\d{2}:\d{2}\b", line):
            if last_tx_index is not None and txs[last_tx_index].type != "BALANCE":
                prev = txs[last_tx_index]
                txs[last_tx_index] = _Tx(
                    transactionDate=prev.transactionDate,
                    description=_clean_description(prev.description + " " + line),
                    amount=prev.amount,
                    balance=prev.balance,
                    type=prev.type,
                )
            continue

        full_dm = _DATE_PREFIX_RE.match(line)
        if full_dm:
            dd, mm, yyyy = int(full_dm.group(1)), int(full_dm.group(2)), int(full_dm.group(3))
            try:
                current_date = date(yyyy, mm, dd)
            except ValueError:
                current_date = None
            body = line[full_dm.end() :].strip()
        else:
            short_dm = _DAY_PREFIX_RE.match(line)
            if short_dm:
                day = int(short_dm.group(1))
                try:
                    current_date = date(fallback_year, fallback_month, day)
                except ValueError:
                    current_date = None
                body = line[short_dm.end() :].strip()
            else:
                body = line

        if current_date is None:
            if last_tx_index is not None and txs[last_tx_index].type != "BALANCE":
                prev = txs[last_tx_index]
                txs[last_tx_index] = _Tx(
                    transactionDate=prev.transactionDate,
                    description=_clean_description(prev.description + " " + line),
                    amount=prev.amount,
                    balance=prev.balance,
                    type=prev.type,
                )
            continue

        lower_body = _strip_accents(body).lower()
        amount_raw, dc, amount_idx = _extract_primary_amount(body)

        if _is_balance_description(body):
            if amount_raw is None:
                warnings.append("unparsed_balance_row")
                continue

            balance_value = abs(amount_raw)
            if dc == "D":
                balance_value = -abs(balance_value)
            elif dc == "C":
                balance_value = abs(balance_value)
            elif amount_raw < 0:
                balance_value = amount_raw

            balances_by_date[current_date] = balance_value
            txs.append(
                _Tx(
                    transactionDate=current_date,
                    description="SALDO DO DIA",
                    amount=Decimal("0.00"),
                    balance=balance_value,
                    type="BALANCE",
                )
            )
            last_tx_index = len(txs) - 1
            continue

        if amount_raw is None or amount_idx is None:
            if (
                last_tx_index is not None
                and txs[last_tx_index].type != "BALANCE"
                and _is_continuation_line(body)
            ):
                prev = txs[last_tx_index]
                txs[last_tx_index] = _Tx(
                    transactionDate=prev.transactionDate,
                    description=_clean_description(prev.description + " " + body),
                    amount=prev.amount,
                    balance=prev.balance,
                    type=prev.type,
                )
            else:
                _push_warning(warnings, "missing_amount_on_tx_line")
            continue

        description = _clean_description(body[:amount_idx])
        signed_amount, tx_type = _infer_signed_amount(amount_raw, dc, description)
        if _should_drop_transaction(description, signed_amount.quantize(Decimal("0.01"))):
            continue

        txs.append(
            _Tx(
                transactionDate=current_date,
                description=description,
                amount=signed_amount,
                balance=None,
                type=tx_type,
            )
        )
        last_tx_index = len(txs) - 1

    statement_date = period_end
    if statement_date is None and txs:
        statement_date = max(t.transactionDate for t in txs)

    opening: Decimal | None = None
    closing: Decimal | None = None
    if balances_by_date:
        ordered = sorted(balances_by_date)
        opening = balances_by_date[ordered[0]]
        closing = balances_by_date[ordered[-1]]

    debug.update(
        {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "statementDate": statement_date.isoformat() if statement_date else None,
            "txCount": len(txs),
            "balanceDays": len(balances_by_date),
        }
    )

    result: dict[str, Any] = {
        "bank": "BANCO_DO_BRASIL",
        "statementDate": statement_date.isoformat() if statement_date else None,
        "openingBalance": float((opening or Decimal("0.00")).quantize(Decimal("0.01"))),
        "closingBalance": float((closing or Decimal("0.00")).quantize(Decimal("0.01"))),
        "transactions": [
            {
                "transactionDate": tx.transactionDate.isoformat(),
                "description": tx.description,
                "amount": float(tx.amount.quantize(Decimal("0.01"))),
                "balance": float(tx.balance.quantize(Decimal("0.01"))) if tx.balance is not None else None,
                "type": tx.type,
            }
            for tx in txs
        ],
    }

    if not result["transactions"] or not result["statementDate"]:
        result["reason"] = "UNSUPPORTED_LAYOUT"

    return result, warnings, debug
