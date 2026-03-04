from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


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


_DUE_WITH_YEAR = re.compile(r"(?is)\b(?:venc(?:imento)?|vct(?:o)?|data\s+de\s+vencimento)\b[^0-9]{0,30}(\d{2})[\./-](\d{2})[\./-](\d{4})")
_DUE_NO_YEAR = re.compile(r"(?is)\b(?:venc(?:imento)?|vct(?:o)?|data\s+de\s+vencimento)\b[^0-9]{0,30}(\d{2})[\./-](\d{2})(?![\./-]\d{4})")
_ANY_FULL_DATE = re.compile(r"\b\d{2}/\d{2}/(\d{4})\b")


def extract_due_date(text: str) -> date | None:
    n = normalize_text(text)

    m = _DUE_WITH_YEAR.search(n)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    m = _DUE_NO_YEAR.search(n)
    if m:
        inferred_year = None
        y = _ANY_FULL_DATE.search(n)
        if y:
            try:
                inferred_year = int(y.group(1))
            except ValueError:
                inferred_year = None
        if inferred_year is None:
            inferred_year = date.today().year
        try:
            return date(inferred_year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    return None


_TOTAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?is)\btotal\s+da\s+fatura\b[^0-9]{0,25}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    re.compile(r"(?is)\btotal\b[^0-9]{0,25}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
]


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
    n = _flat(text)
    for pat in _TOTAL_PATTERNS:
        m = pat.search(n)
        if not m:
            continue
        amount = _parse_brl_money(m.group(1))
        if amount is None:
            continue
        return float(amount.copy_abs().quantize(Decimal("0.01")))
    return None


_TX_LINE = re.compile(r"^(\d{2}/\d{2})\s+(.+?)\s+(?:([A-Z]{2})\s+)?R\$\s*([\-\d\.,]+)\s*$")
_CARD_FINAL = re.compile(r"(?i)\bfinal\s+(\d{4})\b")


def _parse_purchase_date(ddmm: str, due: date | None) -> date | None:
    if due is None:
        return None
    parts = ddmm.split("/")
    if len(parts) != 2:
        return None
    try:
        day, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None

    year = due.year - 1 if month > due.month else due.year
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _is_detail_line(line: str, nline: str) -> bool:
    if line.startswith("***"):
        return True
    return nline.startswith("cotacao") or nline.startswith("iof")


def _is_category_header(line: str) -> bool:
    headers = {
        "lazer",
        "restaurantes",
        "servicos",
        "vestuario",
        "viagens",
        "outros lancamentos",
    }
    return _normalize_for_search(line) in headers


def _is_previous_invoice_payment(description: str) -> bool:
    n = _normalize_for_search(description)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n.startswith("pgto cobranca") or n.startswith("pagto cobranca") or n.startswith("pagamento cobranca")


def _infer_type(description: str, signed_amount: Decimal) -> str:
    if signed_amount < 0:
        return "INCOME"
    n = _normalize_for_search(description)
    if any(token in n for token in ("pgto", "pagamento", "credito", "estorno", "reembolso")):
        return "INCOME"
    return "EXPENSE"


def extract_transactions(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    due = extract_due_date(normalized)
    if due is None:
        return []

    in_transactions = False
    skipping_intl_continuation = False
    card_final: str | None = None
    txs: list[dict[str, Any]] = []

    for raw in normalized.split("\n"):
        line = (raw or "").strip()
        if not line:
            continue

        nline = _normalize_for_search(line)

        m_final = _CARD_FINAL.search(line)
        if m_final:
            card_final = m_final.group(1)

        if not in_transactions:
            if "descricao" in nline and "valor" in nline and "pais" in nline:
                in_transactions = True
            continue

        if "total da fatura" in nline or ("resumo" in nline and "fatura" in nline):
            break

        if _is_category_header(line):
            continue

        if skipping_intl_continuation:
            if raw and raw[0].isspace():
                continue
            skipping_intl_continuation = False

        m = _TX_LINE.search(line)
        if not m:
            if _is_detail_line(line, nline):
                continue
            continue

        ddmm = m.group(1).strip()
        description = m.group(2).strip()
        country = (m.group(3) or "").strip()
        amount_raw = (m.group(4) or "").strip()

        if not description or _is_previous_invoice_payment(description):
            continue

        purchase_date = _parse_purchase_date(ddmm, due)
        amount = _parse_brl_money(amount_raw)
        if purchase_date is None or amount is None:
            continue

        tx: dict[str, Any] = {
            "date": purchase_date.isoformat(),
            "description": description,
            "amount": float(amount.copy_abs().quantize(Decimal("0.01"))) if _infer_type(description, amount) == "EXPENSE" else -float(amount.copy_abs().quantize(Decimal("0.01"))),
        }
        if card_final:
            tx["cardFinal"] = card_final

        txs.append(tx)

        if country and country.upper() != "BR":
            skipping_intl_continuation = True

    return txs


def parse_banco_do_brasil(text: str) -> dict[str, Any]:
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
        "bank": "BANCO_DO_BRASIL",
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
            "sourceParser": "parsers.invoices.banco_do_brasil",
            "notes": [
                "Contract v1 is additive and backward-compatible.",
                "Top-level fields bank/dueDate/total/transactions are preserved.",
            ],
        },
    }
