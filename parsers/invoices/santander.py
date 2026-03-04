from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

_CID_PATTERN = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

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


def _parse_brl_money(value: str) -> Decimal | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    s = s.replace("−", "-").replace("–", "-").replace("—", "-")
    sign = -1 if s.startswith("-") else 1

    s = re.sub(r"[^0-9,\.]", "", s)
    if not s:
        return None

    s = s.replace(".", "").replace(",", ".")

    try:
        return Decimal(s) * sign
    except InvalidOperation:
        return None


_DUE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\bvencimento\b[^0-9]{0,20}(\d{1,2}/\d{1,2}/\d{2,4})"),
    re.compile(r"(?i)\btotal\s*a\s*pagar\b[^0-9]{0,20}(\d{1,2}/\d{1,2}/\d{2,4})"),
]

_DATE_WITH_YEAR_RE = re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")


def _parse_dmy_token(token: str) -> date | None:
    parts = token.split("/")
    if len(parts) != 3:
        return None

    try:
        dd, mm, yy = int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None

    year = 2000 + yy if yy < 100 else yy
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def extract_due_date(text: str) -> date | None:
    n = normalize_text(text)

    for p in _DUE_PATTERNS:
        m = p.search(n)
        if not m:
            continue
        parsed = _parse_dmy_token(m.group(1))
        if parsed is not None:
            return parsed

    # Some Santander PDFs present a compact header/table where "Vencimento"
    # is followed by other numeric tokens (e.g., "até 15/12") before the real
    # due date with year. In this case, scan a local window and pick the first
    # full date token (dd/mm/yyyy).
    low = n.lower()
    idx = low.find("vencimento")
    if idx >= 0:
        window = n[idx : idx + 260]
        for m in _DATE_WITH_YEAR_RE.finditer(window):
            parsed = _parse_dmy_token(m.group(0))
            if parsed is not None:
                return parsed

    return None


_TOTAL_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)\btotal\s*a\s*pagar\b[^0-9]{0,20}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    re.compile(r"(?i)\bsaldo\s+desta\s+fatura\b[^0-9]{0,20}(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
]


def extract_total(text: str) -> float | None:
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


_CARD_FINAL_RE = re.compile(r"(?i)\b(\d{4})\s+XXXX\s+XXXX\s+(\d{4})\b")
_DATE_PREFIX_RE = re.compile(r"(\d{1,2})/(\d{1,2})\b")
_AMOUNT_TOKEN_RE = re.compile(r"[\-−–—]?\d{1,3}(?:\.\d{3})*,\d{2}")
_INSTALLMENT_RE = re.compile(r"\b(\d{2})/(\d{2})\b")
_TAIL_AMOUNTS_RE = re.compile(
    r"^(?P<head>.*?)(?P<brl>[\-−–—]?\d{1,3}(?:\.\d{3})*,\d{2})(?:\s+(?P<fx>[\-−–—]?\d{1,3}(?:\.\d{3})*,\d{2}))?\s*$"
)
_MERGED_NEXT_ROW_WITH_PREFIX_RE = re.compile(r"\s\d{1,2}\s+\d{1,2}/\d{1,2}\s+[A-Z@]")
_MERGED_NEXT_ROW_NO_PREFIX_RE = re.compile(r"\s\d{1,2}/\d{1,2}\s+[A-Z@]")


def _is_section_header(line: str) -> bool:
    if _DATE_PREFIX_RE.search(line or ""):
        return False

    low = line.lower().strip()
    if not low:
        return True
    headers = (
        "detalhamento da fatura",
        "pagamento e demais créditos",
        "pagamentos e demais créditos",
        "despesas",
        "parcelamentos",
        "resumo da fatura",
        "saldo total consolidado de obrigações futuras",
        "compra data descrição",
        "compra data descricao",
        "descrição",
        "descricao",
        "valor total",
        "total cartão",
        "total cartao",
    )
    return any(h in low for h in headers)


def _should_skip_description(desc: str) -> bool:
    n = re.sub(r"\s+", " ", (desc or "").strip().lower())
    if not n:
        return True

    if "pagamento de fatura" in n:
        return True
    if n.startswith("resumo da fatura"):
        return True

    return False


def _is_financial_summary_line(line: str) -> bool:
    n = re.sub(r"\s+", " ", (line or "").strip().lower())
    if not n:
        return True

    markers = (
        "vencimento",
        "total a pagar",
        "saldo anterior",
        "saldo desta fatura",
        "total despesas",
        "total de despesas",
        "total pagamentos",
        "total de pagamentos",
        "total creditos",
        "total de creditos",
        "total créditos",
        "total de créditos",
    )
    return any(marker in n for marker in markers)


def _parse_purchase_date(dd: int, mm: int, due: date | None) -> date | None:
    if due is None:
        year = date.today().year
    else:
        year = due.year - 1 if mm > due.month else due.year
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def _split_line_into_date_segments(line: str) -> list[str]:
    raw = (line or "").strip()
    if not raw:
        return []

    parts: list[str] = []
    current = raw

    while current:
        m = _MERGED_NEXT_ROW_WITH_PREFIX_RE.search(current)
        if not m:
            m = _MERGED_NEXT_ROW_NO_PREFIX_RE.search(current)

        if not m:
            parts.append(current.strip())
            break

        left = current[: m.start()].strip()
        right = current[m.start() :].strip()
        if left:
            parts.append(left)
        current = right

    return [p for p in parts if _DATE_PREFIX_RE.search(p)]


def _strip_trailing_noise(rest: str) -> str:
    if not rest:
        return rest

    low = rest.lower()
    markers = (
        " cotação dolar",
        " cotacao dolar",
        " iof despesa no exterior",
        " valor total",
        " explore descontos",
    )
    cut = len(rest)
    for marker in markers:
        idx = low.find(marker)
        if idx >= 0:
            cut = min(cut, idx)

    return rest[:cut].strip()


def _extract_brl_amount_and_head(rest: str) -> tuple[Decimal | None, str | None]:
    if not rest:
        return None, None

    # Prefer trailing table-like parsing: in Santander detailed rows,
    # when two values are present at the end, first is BRL (R$) and second is FX (US$).
    tail = _TAIL_AMOUNTS_RE.match(rest)
    if tail:
        brl_raw = tail.group("brl")
        brl = _parse_brl_money(brl_raw)
        if brl is not None:
            return brl, (tail.group("head") or "").strip()

    # Fallback for noisier lines: keep legacy behavior.
    amount_matches = list(_AMOUNT_TOKEN_RE.finditer(rest))
    if not amount_matches:
        return None, None

    chosen = amount_matches[-1]
    if len(amount_matches) >= 2:
        last_val = _parse_brl_money(amount_matches[-1].group(0))
        prev_val = _parse_brl_money(amount_matches[-2].group(0))
        if last_val is not None and prev_val is not None and abs(last_val) == Decimal("0") and abs(prev_val) > Decimal("0"):
            chosen = amount_matches[-2]

    amount = _parse_brl_money(chosen.group(0))
    if amount is None:
        return None, None

    return amount, rest[: chosen.start()].strip()


def extract_transactions(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    due = extract_due_date(normalized)
    txs: list[dict[str, Any]] = []

    current_card_final: str | None = None

    for raw in normalized.split("\n"):
        line = (raw or "").strip()
        if not line:
            continue

        m_card = _CARD_FINAL_RE.search(line)
        if m_card:
            current_card_final = m_card.group(2)

        if _is_section_header(line):
            continue
        if _is_financial_summary_line(line):
            continue

        for seg in _split_line_into_date_segments(line):
            m_date = _DATE_PREFIX_RE.search(seg)
            if not m_date:
                continue

            # Ignore full dates (dd/mm/yyyy or dd/mm/yy), common on header lines
            # like "Vencimento 25/02/2026 R$ ...".
            if m_date.end() < len(seg) and seg[m_date.end()] == "/":
                continue

            dd = int(m_date.group(1))
            mm = int(m_date.group(2))

            rest = seg[m_date.end() :].strip()
            if not rest:
                continue

            rest = _strip_trailing_noise(rest)
            if not rest:
                continue

            amount, left = _extract_brl_amount_and_head(rest)
            if amount is None:
                continue

            installment: dict[str, int] | None = None
            m_inst = None
            for m in _INSTALLMENT_RE.finditer(left):
                m_inst = m
            if m_inst:
                try:
                    installment = {"current": int(m_inst.group(1)), "total": int(m_inst.group(2))}
                    left = (left[: m_inst.start()] + " " + left[m_inst.end() :]).strip()
                except ValueError:
                    installment = None

            desc = re.sub(r"\s+", " ", left).strip(" -")
            if _should_skip_description(desc):
                continue

            purchase_date = _parse_purchase_date(dd, mm, due)
            if purchase_date is None:
                continue

            tx: dict[str, Any] = {
                "date": purchase_date.isoformat(),
                "description": desc,
                "amount": float(amount.quantize(Decimal("0.01"))),
            }

            if current_card_final:
                tx["cardFinal"] = current_card_final
            if installment:
                tx["installment"] = installment

            txs.append(tx)

    return txs


def parse_santander(text: str) -> dict[str, Any]:
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
        "bank": "SANTANDER",
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
            "sourceParser": "parsers.invoices.santander",
            "notes": [
                "Contract v1 is additive and backward-compatible.",
                "Top-level fields bank/dueDate/total/transactions are preserved.",
            ],
        },
    }
