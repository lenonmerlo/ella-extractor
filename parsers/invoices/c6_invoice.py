from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_MONTHS_PT: dict[str, int] = {
    "jan": 1,
    "fev": 2,
    "mar": 3,
    "abr": 4,
    "mai": 5,
    "jun": 6,
    "jul": 7,
    "ago": 8,
    "set": 9,
    "out": 10,
    "nov": 11,
    "dez": 12,
}


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    out: list[str] = []
    blank_run = 0
    for raw in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", raw).strip()
        if not line:
            blank_run += 1
            if blank_run <= 1:
                out.append("")
            continue
        blank_run = 0
        out.append(line)

    return "\n".join(out).strip()


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", normalize_text(text)).strip()


def _normalize_for_search(value: str) -> str:
    s = value.lower()
    s = s.replace("ç", "c")
    s = s.replace("ã", "a").replace("á", "a").replace("à", "a")
    s = s.replace("é", "e").replace("ê", "e")
    s = s.replace("í", "i")
    s = s.replace("ó", "o").replace("ô", "o")
    s = s.replace("ú", "u")
    return re.sub(r"\s+", " ", s).strip()


_DUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?is)\b(?:venc(?:imento)?|data\s+de\s+vencimento|data\s+do\s+vencimento)\b[^0-9]{0,40}(\d{2})[\./-](\d{2})[\./-](\d{4})"),
    re.compile(r"(?is)\b(?:venc(?:imento)?|data\s+de\s+vencimento|data\s+do\s+vencimento)\b[^0-9]{0,60}(\d{2})\s+(?:de\s+)?([a-z]{3,9})\s+(\d{4})"),
    re.compile(r"(?is)\b(?:venc(?:imento)?|data\s+de\s+vencimento|data\s+do\s+vencimento)\b[^0-9]{0,40}(\d{2})[\./-](\d{2})(?![\./-]\d{4})"),
]

_YEAR_FROM_TEXT = re.compile(r"\b\d{2}/\d{2}/(\d{4})\b")


def _month_to_int(token: str) -> int | None:
    if not token:
        return None
    clean = re.sub(r"[^a-z0-9]", "", _normalize_for_search(token))
    # OCR: n0v -> nov
    clean = clean.replace("0", "o")
    if len(clean) >= 3:
        clean = clean[:3]
    return _MONTHS_PT.get(clean)


def extract_due_date(text: str) -> date | None:
    n = normalize_text(text)
    inferred_year = None
    y = _YEAR_FROM_TEXT.search(n)
    if y:
        try:
            inferred_year = int(y.group(1))
        except ValueError:
            inferred_year = None

    for p in _DUE_PATTERNS:
        m = p.search(n)
        if not m:
            continue

        if len(m.groups()) == 3 and m.group(2).isdigit():
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue

        if len(m.groups()) == 3 and not m.group(2).isdigit():
            mm = _month_to_int(m.group(2))
            if mm is None:
                continue
            try:
                return date(int(m.group(3)), mm, int(m.group(1)))
            except ValueError:
                continue

        if len(m.groups()) >= 2:
            try:
                dd = int(m.group(1))
                mm = int(m.group(2))
            except ValueError:
                continue
            yy = inferred_year if inferred_year is not None else date.today().year
            try:
                return date(yy, mm, dd)
            except ValueError:
                continue

    return None


_TOTAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?is)\btotal\s+a\s+pagar\b[^0-9]{0,30}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    re.compile(r"(?is)\bvalor\s+da\s+fatura\b[^0-9]{0,30}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    re.compile(r"(?is)\btotal\s+da\s+fatura\b[^0-9]{0,30}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    re.compile(r"(?is)\bchegou\s+no\s+valor\s+de\b[^0-9]{0,30}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
]

_MONEY_IN_LINE = re.compile(r"(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})")


def _extract_totals_from_lines(text: str) -> list[Decimal]:
    candidates: list[Decimal] = []
    for raw in normalize_text(text).split("\n"):
        line = raw.strip()
        if not line:
            continue

        normalized = _normalize_for_search(line)
        if (
            "total a pagar" not in normalized
            and "valor da fatura" not in normalized
            and "total da fatura" not in normalized
            and "chegou no valor" not in normalized
        ):
            continue

        for m in _MONEY_IN_LINE.finditer(line):
            amount = _parse_brl_money(m.group(1))
            if amount is not None:
                candidates.append(amount.copy_abs().quantize(Decimal("0.01")))

    return candidates


def _parse_brl_money(value: str) -> Decimal | None:
    if value is None:
        return None
    s = value.strip().replace("−", "-").replace("–", "-").replace("—", "-")
    if not s:
        return None

    sign = -1 if s.startswith("-") else 1
    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return None
    s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s) * sign
    except InvalidOperation:
        return None


def extract_total(text: str) -> float | None:
    line_candidates = _extract_totals_from_lines(text)
    if line_candidates:
        most_common = max(set(line_candidates), key=line_candidates.count)
        return float(most_common)

    n = _flat(text)
    for p in _TOTAL_PATTERNS:
        m = p.search(n)
        if not m:
            continue
        amount = _parse_brl_money(m.group(1))
        if amount is None:
            continue
        return float(amount.copy_abs().quantize(Decimal("0.01")))
    return None


_CARD_HEADER = re.compile(r"(?i)^c6\s+(.+?)\s+final\s*:?\s*(\d{4})(?:\s*-\s*(.+))?$")
_TX_LINE = re.compile(r"(?i)^(\d{1,2})\s+([a-z0-9]{3})\s+(.+?)(?:\s+-\s+parcela\s+(\d+)\s*/\s*(\d+))?\s+(-?[\d\.,]+)\s*$")


def _is_payment_from_previous_invoice(description: str) -> bool:
    n = _normalize_for_search(description)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return "inclusao de pagamento" in n or "inclusao pagamento" in n


def _infer_signed_amount(description: str, raw_amount: Decimal) -> Decimal:
    n = _normalize_for_search(description)
    if any(token in n for token in ("estorno", "credito", "reembolso", "pagamento")):
        return raw_amount.copy_abs() * Decimal(-1)
    return raw_amount


def _build_purchase_date(day: int, mon_token: str, due: date | None) -> date | None:
    mm = _month_to_int(mon_token)
    if mm is None:
        return None

    if due is None:
        yy = date.today().year
    else:
        yy = due.year if mm <= due.month else due.year - 1

    try:
        return date(yy, mm, day)
    except ValueError:
        return None


def extract_transactions(text: str) -> list[dict[str, Any]]:
    n = normalize_text(text)
    if not n:
        return []

    due = extract_due_date(n)
    current_card_final: str | None = None
    txs: list[dict[str, Any]] = []

    for raw in n.split("\n"):
        line = (raw or "").strip()
        if not line:
            continue

        line = line.replace("|", " ")
        line = re.sub(r"\s+", " ", line).strip()
        nline = _normalize_for_search(line)

        if "subtotal deste cartao" in nline:
            current_card_final = None
            continue

        m_card = _CARD_HEADER.search(line)
        if m_card:
            current_card_final = (m_card.group(2) or "").strip() or None
            continue

        m_tx = _TX_LINE.search(line)
        if not m_tx:
            continue

        try:
            dd = int(m_tx.group(1))
        except ValueError:
            continue

        mon = (m_tx.group(2) or "").strip()
        desc = (m_tx.group(3) or "").strip()
        inst_num = m_tx.group(4)
        inst_tot = m_tx.group(5)
        amount_raw = _parse_brl_money((m_tx.group(6) or "").strip())

        if not desc or amount_raw is None:
            continue

        if _is_payment_from_previous_invoice(desc):
            continue

        purchase_date = _build_purchase_date(dd, mon, due)
        if purchase_date is None:
            continue

        signed_amount = _infer_signed_amount(desc, amount_raw)

        tx: dict[str, Any] = {
            "date": purchase_date.isoformat(),
            "description": desc,
            "amount": float(signed_amount.copy_abs().quantize(Decimal("0.01"))) if signed_amount >= 0 else -float(signed_amount.copy_abs().quantize(Decimal("0.01"))),
        }
        if current_card_final:
            tx["cardFinal"] = current_card_final
        if inst_num and inst_tot:
            try:
                tx["installment"] = {"current": int(inst_num), "total": int(inst_tot)}
            except ValueError:
                pass

        txs.append(tx)

    return txs


def parse_c6_invoice(text: str) -> dict[str, Any]:
    due = extract_due_date(text)
    total = extract_total(text)
    txs = extract_transactions(text)

    signed_sum = round(sum(float(t.get("amount", 0) or 0) for t in txs), 2)
    expenses_total = round(sum(float(t.get("amount", 0) or 0) for t in txs if float(t.get("amount", 0) or 0) > 0), 2)
    credits_total_abs = round(sum(abs(float(t.get("amount", 0) or 0)) for t in txs if float(t.get("amount", 0) or 0) < 0), 2)

    reconciliation_diff = None
    is_balanced = None
    if total is not None:
        reconciliation_diff = round(float(total) - signed_sum, 2)
        is_balanced = abs(reconciliation_diff) <= 0.01

    return {
        "parserContractVersion": "1.0.0",
        "bank": "C6",
        "dueDate": due.isoformat() if due else None,
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
            "sourceParser": "parsers.invoices.c6_invoice",
            "notes": [
                "Contract v1 is additive and backward-compatible.",
                "Top-level fields bank/dueDate/total/transactions are preserved.",
            ],
        },
    }
