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


_CID_PATTERN = re.compile(r"\(cid:\d+\)")


def normalize_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ").replace("\xa0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CID_PATTERN.sub("", text)

    cleaned_lines: list[str] = []
    for line in text.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        cleaned_lines.append(line)

    # collapse excessive blank lines
    out: list[str] = []
    blank_run = 0
    for ln in cleaned_lines:
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


_DUE_DATE_DDMMYYYY = re.compile(r"(?i)\bvencimento\b\s*(?:[:\-])?\s*(\d{2})/(\d{2})/(\d{4})\b")
_DUE_DATE_DD_MON = re.compile(r"(?i)\bvencimento\b\s*(?:[:\-])?\s*(\d{2})\s*/\s*([a-z]{3})\b")


def extract_due_date(text: str) -> date | None:
    n = _flat(text)

    m = _DUE_DATE_DDMMYYYY.search(n)
    if m:
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(yyyy, mm, dd)
        except ValueError:
            return None

    m = _DUE_DATE_DD_MON.search(n)
    if m:
        dd = int(m.group(1))
        mon = m.group(2).lower()
        mm = _MONTHS_PT.get(mon)
        if not mm:
            return None

        # infer year from any explicit dd/MM/yyyy in the document, else fallback to current year
        year = None
        any_year = re.search(r"\b\d{2}/\d{2}/(\d{4})\b", n)
        if any_year:
            try:
                year = int(any_year.group(1))
            except ValueError:
                year = None

        if year is None:
            year = date.today().year

        try:
            return date(year, mm, dd)
        except ValueError:
            return None

    return None


def _parse_brl_money(value: str) -> Decimal | None:
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None

    sign = -1 if s.lstrip().startswith("-") or "-R$" in s.replace(" ", "") else 1

    # Keep digits and separators
    s = re.sub(r"[^0-9,\.]", "", s)
    s = s.replace(".", "").replace(",", ".")

    try:
        d = Decimal(s)
    except InvalidOperation:
        return None

    return d * sign


_TOTAL_PATTERNS: list[re.Pattern[str]] = [
    # "Total fatura de novembro R$ 12.068,55"
    re.compile(r"(?i)total\s+fatura\s+de\s+\w+\s*r\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    # "Pagamento total (R$) R$ 12.068,55"
    re.compile(r"(?i)pagamento\s+total\s*\(r\$\)\s*r\$\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    # "Total desta Fatura 12.068,55" (com ou sem R$)
    re.compile(r"(?i)total\s+desta\s+fatura\s*(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
    # "Total desta Fatura" pode vir "Total desta Fatura (R$) 12.068,55"
    re.compile(r"(?i)total\s+desta\s+fatura\s*\(r\$\)\s*([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})"),
]


def extract_total(text: str) -> float | None:
    n = _flat(text)

    for pat in _TOTAL_PATTERNS:
        m = pat.search(n)
        if not m:
            continue
        d = _parse_brl_money(m.group(1))
        if d is None:
            continue
        return float(d.copy_abs().quantize(Decimal("0.01")))

    return None


_CARD_FINAL_RE = re.compile(r"(?i)\bfinal\s+(\d{4})\b")
_CARD_FINAL_BARE_RE = re.compile(r"^\s*(\d{4})\b")

# Typical tx line starts with "11/nov 06:13 ..."
_TX_PREFIX_RE = re.compile(r"^\s*(\d{2})/([a-z]{3})\s+(\d{2}:\d{2})\b\s+(.*)$", re.IGNORECASE)

# Amount at end: "R$ 4,90", "-R$ 198,00", sometimes without space.
_AMOUNT_AT_END_RE = re.compile(
    r"(?i)\s*(-?\s*R\$\s*)?(-?\d{1,3}(?:\.\d{3})*,\d{2})\s*$"
)

_INSTALLMENT_RE = re.compile(r"\b(\d{2})/(\d{2})\b")


def _extract_summary_iof(text: str) -> Decimal | None:
    """Try to extract the IOF amount shown in the invoice summary (not the per-transaction IOF lines)."""
    normalized = normalize_text(text)
    if not normalized:
        return None

    for raw in normalized.split("\n"):
        line = (raw or "").strip()
        if not line:
            continue
        low = line.lower()
        if not low.startswith("iof"):
            continue
        # Avoid picking up the transaction line "Iof Compra Internacional"
        if "compra" in low:
            continue

        m = re.search(r"(?i)\biof\b\s*(?:\(r\$\))?\s*(?:r\$\s*)?([0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\b", line)
        if not m:
            continue

        return _parse_brl_money(m.group(1))

    return None


def _should_skip_description(desc: str) -> bool:
    if not desc:
        return True
    n = re.sub(r"\s+", " ", desc).strip().lower()

    # Payments of previous invoice show up as credits; exclude to avoid polluting spend.
    if n.startswith("pagamento"):
        if re.match(r"^pagamento\s+\d{6,}\b", n):
            return True
        if "fatura" in n:
            return True

    return False


def _parse_tx_line(rest: str) -> tuple[str, str | None, dict[str, int] | None, str | None]:
    """Return (description, purchase_type, installment, card_final_override)."""

    card_final_override = None
    m_final = _CARD_FINAL_RE.search(rest)
    if m_final:
        card_final_override = m_final.group(1)

    installment: dict[str, int] | None = None
    m_inst = _INSTALLMENT_RE.search(rest)
    if m_inst:
        try:
            installment = {"current": int(m_inst.group(1)), "total": int(m_inst.group(2))}
        except ValueError:
            installment = None

    purchase_type: str | None = None
    m_type = re.search(r"\b(Online|Presencial)\b", rest, flags=re.IGNORECASE)
    if m_type:
        purchase_type = m_type.group(1).capitalize()

    # Heuristic: if we have Online/Presencial, prefer text after it as description.
    desc = rest
    if m_type:
        desc = rest[m_type.end() :].strip()

    # Remove installment tokens lingering in description
    if installment:
        desc = _INSTALLMENT_RE.sub(" ", desc)

    # Clean repeated spaces
    desc = re.sub(r"\s+", " ", desc).strip()

    return desc, purchase_type, installment, card_final_override


def _is_context_description_line(line: str) -> bool:
    if not line:
        return False
    if _TX_PREFIX_RE.match(line):
        return False

    low = line.strip().lower()
    if not low:
        return False

    # Avoid using headers/totals/pages as descriptions.
    if low.startswith("total cartão") or low.startswith("total cartao"):
        return False
    if low.startswith("cartão ") or low.startswith("cartao "):
        return False
    if low.startswith("vencimento"):
        return False
    if low.endswith(" de 7") or low.endswith(" de 6") or low.endswith(" de 5"):
        return False

    # If it's just a value line, ignore.
    if _AMOUNT_AT_END_RE.fullmatch(low):
        return False

    return True


def extract_transactions(text: str) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not normalized:
        return []

    due = extract_due_date(normalized)
    year = due.year if due else date.today().year

    txs: list[dict[str, Any]] = []

    current_card_final: str | None = None
    in_transactions = False
    last_context_line: str | None = None

    pending: dict[str, Any] | None = None

    for raw in normalized.split("\n"):
        line = (raw or "").strip()
        if not line:
            continue

        # Track card final when present.
        m_final = _CARD_FINAL_RE.search(line)
        if m_final:
            current_card_final = m_final.group(1)

        low = line.lower()
        if "data e hora" in low and "valor em reais" in low:
            in_transactions = True
            continue

        # Sometimes the section header is present.
        if low.strip() == "transações" or low.strip() == "transacoes":
            in_transactions = True
            continue

        # Capture possible description context lines that appear *before* the tx line.
        if in_transactions and not _TX_PREFIX_RE.match(line) and _is_context_description_line(line):
            last_context_line = line

        # Handle continuation line for split transactions (amount on next line)
        if pending is not None and not _TX_PREFIX_RE.match(line):
            amount_m = _AMOUNT_AT_END_RE.search(line)
            if amount_m:
                amount_token = (amount_m.group(1) or "") + amount_m.group(2)
                amount = _parse_brl_money(amount_token)
                if amount is not None:
                    # Optional bare card final at start of continuation line (e.g. "2127  R$ 58,33")
                    card_final = pending.get("cardFinal")
                    m_bare = _CARD_FINAL_BARE_RE.match(line)
                    if m_bare:
                        card_final = m_bare.group(1)

                    tx: dict[str, Any] = {
                        "date": pending["date"],
                        "description": pending["description"],
                        "amount": float(amount.quantize(Decimal("0.01"))),
                    }
                    if card_final:
                        tx["cardFinal"] = card_final
                    if pending.get("installment"):
                        tx["installment"] = pending["installment"]

                    txs.append(tx)
                    pending = None
            continue

        if not in_transactions and not _TX_PREFIX_RE.match(line):
            continue

        m = _TX_PREFIX_RE.match(line)
        if not m:
            continue

        # If we had a pending split tx and we hit a new tx line, drop pending.
        pending = None

        dd = int(m.group(1))
        mon = m.group(2).lower()
        hhmm = m.group(3)
        rest = m.group(4).strip()

        mm = _MONTHS_PT.get(mon)
        if not mm:
            continue

        amount_m = _AMOUNT_AT_END_RE.search(rest)
        if not amount_m:
            # Split line: keep metadata and wait for the amount on the next line.
            desc, _purchase_type, installment, card_final_override = _parse_tx_line(rest)
            if _should_skip_description(desc):
                continue

            card_final = card_final_override or current_card_final
            try:
                tx_date = date(year, mm, dd)
            except ValueError:
                continue

            pending = {
                "date": tx_date.isoformat(),
                "description": desc,
                "cardFinal": card_final,
                "installment": installment,
            }
            continue

        amount_token = (amount_m.group(1) or "") + amount_m.group(2)
        amount = _parse_brl_money(amount_token)
        if amount is None:
            continue

        rest_wo_amount = rest[: amount_m.start()].strip()
        # Some PDFs split: description is on the previous line, and the tx line only contains the amount.
        if not rest_wo_amount and last_context_line:
            rest_wo_amount = last_context_line
            last_context_line = None
        desc, _purchase_type, installment, card_final_override = _parse_tx_line(rest_wo_amount)
        if _should_skip_description(desc):
            continue

        card_final = card_final_override or current_card_final

        try:
            tx_date = date(year, mm, dd)
        except ValueError:
            continue

        tx: dict[str, Any] = {
            "date": tx_date.isoformat(),
            "description": desc,
            "amount": float(amount.quantize(Decimal("0.01"))),
        }
        if card_final:
            tx["cardFinal"] = card_final
        if installment:
            tx["installment"] = installment

        txs.append(tx)

    return txs


def parse_sicredi(text: str) -> dict[str, Any]:
    due = extract_due_date(text)
    total = extract_total(text)
    txs = extract_transactions(text)

    # If the invoice has a summary IOF not listed as a transaction, add it.
    # This helps reconcile the signed sum of transactions with the header total.
    if total is not None and due is not None:
        signed_sum = sum(float(t.get("amount", 0) or 0) for t in txs)
        diff = round(float(total) - signed_sum, 2)

        if abs(diff) >= 0.01:
            iof = _extract_summary_iof(text)
            if iof is not None and float(iof.copy_abs().quantize(Decimal("0.01"))) == abs(diff):
                txs.append(
                    {
                        "date": due.isoformat(),
                        "description": "IOF (fatura)",
                        "amount": float(iof.copy_abs().quantize(Decimal("0.01"))),
                    }
                )

    return {
        "bank": "SICREDI",
        "dueDate": due.isoformat() if due else None,
        "total": total,
        "transactions": txs,
    }
