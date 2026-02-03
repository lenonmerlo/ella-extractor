from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


_CID_PATTERN = re.compile(r"\(cid:\d+\)")


_MONTHS_PT_ABBR: dict[str, int] = {
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

_MONTHS_PT_FULL: dict[str, int] = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "março": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def normalize_text(text: str) -> str:
    """Normaliza texto extraído do PDF preservando quebras de linha."""
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


# Ex: "01 DE DEZEMBRO DE 2025 a 31 DE DEZEMBRO DE 2025"
_PERIOD_RE = re.compile(
    r"(?i)\b(\d{2})\s+de\s+([a-zçãõ]+)\s+de\s+(\d{4})\s*(?:a|\-|at[eé])\s*(\d{2})\s+de\s+([a-zçãõ]+)\s+de\s+(\d{4})\b"
)

# Ex: "22 DEZ 2025"
_DAY_RE = re.compile(r"(?i)^\s*(\d{2})\s+([a-z]{3})\s+(\d{4})\b")

# BRL number (optionally +/-, thousands dot, decimal comma)
_MONEY_RE = re.compile(r"(?:(?P<sign>[+\-−])\s*)?(?P<val>\d{1,3}(?:\.\d{3})*,\d{2})\b")

_CNPJ_RE = re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")
_CPF_MASKED_RE = re.compile(r"[•\*]{3}\.\d{3}\.\d{3}-[•\*]{2}")
_AGENCIA_CONTA_RE = re.compile(r"(?i)\bAg[eê]ncia\s*:?\s*\d+\b")
_CONTA_RE = re.compile(r"(?i)\bConta\s*:?\s*[0-9\-\.\/]+\b")
_PAGE_X_OF_Y_RE = re.compile(r"(?i)\b\d+\s+de\s+\d+\b")


def _parse_month_full(name: str) -> int | None:
    n = _strip_accents((name or "").strip().lower())
    return _MONTHS_PT_FULL.get(n)


def _parse_month_abbr(name: str) -> int | None:
    n = _strip_accents((name or "").strip().lower())
    return _MONTHS_PT_ABBR.get(n)


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


def _last_money_at_end(line: str) -> tuple[Decimal | None, str | None, int | None]:
    """Returns (value, sign, start_index_of_match) for the *last* BRL money-like token at end of line."""

    if not line:
        return None, None, None

    # Find last money token, but ensure it's at the end (ignoring trailing spaces)
    stripped = line.rstrip()
    matches = list(_MONEY_RE.finditer(stripped))
    if not matches:
        return None, None, None

    m = matches[-1]
    if m.end() != len(stripped):
        return None, None, None

    raw_val = m.group("val")
    sign = m.group("sign")
    d = _parse_brl_money(("-" if sign in {"-", "−"} else "") + raw_val)
    return d, sign, m.start()


def _is_noise_line(line: str) -> bool:
    if not line:
        return True

    low = _strip_accents(line).lower().strip()
    if not low:
        return True

    # Common headers/footers and boilerplate
    if low.startswith("tem alguma duvida") or low.startswith("tem alguma dúvida"):
        return True
    if "atendimento" in low and "24h" in low:
        return True
    if "ouvidoria" in low:
        return True
    if "nubank.com.br" in low:
        return True
    if low.startswith("extrato gerado dia"):
        return True
    if _PAGE_X_OF_Y_RE.search(low) and "extrato gerado" in low:
        return True

    # Account holder header noise
    if low.startswith("cpf ") or low == "cpf":
        return True
    if _AGENCIA_CONTA_RE.search(line) or _CONTA_RE.search(line):
        # Lines with Agência/Conta usually are bank metadata, not transaction description.
        return True

    # Pure numeric / routing lines
    if re.fullmatch(r"[0-9.\-\/ ]+", line):
        return True

    # Often printed as an isolated label
    if low in {"cartao de credito", "cartão de crédito"}:
        return True

    return False


def _compact_description(description: str, max_len: int = 90) -> str:
    if not description:
        return ""

    d = re.sub(r"\s+", " ", description).strip()

    # Remove masked CPF and long account metadata
    d = _CPF_MASKED_RE.sub("", d)
    d = _CNPJ_RE.sub("", d)
    d = _AGENCIA_CONTA_RE.sub("", d)
    d = _CONTA_RE.sub("", d)

    # Remove common bank metadata fragments
    d = re.sub(r"\(\d{4}\)", "", d)  # bank code like (0341)
    d = re.sub(r"(?i)\bS\.?A\.?\b", "", d)

    # Clean separators
    d = d.replace("•", "").replace("•••", "")
    d = re.sub(r"\s*-\s*", " - ", d)
    d = re.sub(r"\s+", " ", d).strip(" -")

    # Prefer the most informative prefix: keep up to first 2 chunks split by " - "
    parts = [p.strip() for p in d.split(" - ") if p.strip()]
    if len(parts) > 2:
        d = " - ".join(parts[:2])

    if len(d) > max_len:
        cut = d[: max_len - 1].rstrip()
        # avoid cutting mid-space
        cut = re.sub(r"\s+\S*$", "", cut).strip() or cut
        d = cut + "…"

    return d


def _infer_signed_amount(
    abs_amount: Decimal,
    current_section: str | None,
    description: str,
) -> Decimal:
    if current_section == "DEBIT":
        return -abs_amount
    if current_section == "CREDIT":
        return abs_amount

    low = _strip_accents(description).lower()
    debit_markers = ["enviada", "enviado", "pagamento", "compra", "debito", "débito"]
    credit_markers = ["recebida", "recebido", "adicionado", "entrada", "credito", "crédito"]

    if any(mk in low for mk in debit_markers):
        return -abs_amount
    if any(mk in low for mk in credit_markers):
        return abs_amount

    return abs_amount


def _extract_summary_value(text: str, label: str) -> Decimal | None:
    n = normalize_text(text)
    if not n:
        return None

    # Prefer line-based match
    for ln in n.split("\n"):
        low = _strip_accents(ln).lower()
        if label in low:
            values = list(_MONEY_RE.finditer(ln))
            if values:
                raw = values[-1].group("val")
                sign = values[-1].group("sign")
                return _parse_brl_money(("-" if sign in {"-", "−"} else "") + raw)

    # Fallback: flat search
    flat = _flat(text)
    idx = _strip_accents(flat).lower().find(label)
    if idx >= 0:
        tail = flat[idx : idx + 250]
        values = list(_MONEY_RE.finditer(tail))
        if values:
            raw = values[-1].group("val")
            sign = values[-1].group("sign")
            return _parse_brl_money(("-" if sign in {"-", "−"} else "") + raw)

    return None


def looks_like_nubank_bank_statement(text: str) -> bool:
    n = _strip_accents(_flat(text)).lower()
    if not n:
        return False

    markers = [
        "nubank",
        "nu pagamentos",
        "nu pagamentos s.a",
        "nu financeira",
        "nufinanceira",
        "nubank.com.br",
        "movimentacoes",
        "movimentações",
        "total de entradas",
        "total de saidas",
        "total de saídas",
    ]

    score = sum(1 for mk in markers if mk in n)
    has_brand = ("nubank" in n) or ("nu pagamentos" in n) or ("nu pagamentos s.a" in n)
    has_statement_words = ("movimentacoes" in n) or ("total de entradas" in n)
    return has_brand and has_statement_words and score >= 3


@dataclass(frozen=True)
class ParsedTx:
    transactionDate: date
    description: str
    amount: Decimal
    balance: Decimal | None
    type: str  # DEBIT | CREDIT | BALANCE


def parse_nubank_bank_statement(raw_text: str) -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Parse do extrato bancário do Nubank (Conta). Retorna (result, warnings, debug)."""

    warnings: list[str] = []
    debug: dict[str, Any] = {}

    normalized = normalize_text(raw_text)
    flat = _flat(raw_text)

    if not looks_like_nubank_bank_statement(raw_text):
        return ({"bank": "NUBANK", "transactions": [], "reason": "UNSUPPORTED_LAYOUT"}, ["not_nubank"], debug)

    period_start: date | None = None
    period_end: date | None = None
    m_period = _PERIOD_RE.search(flat)
    if m_period:
        dd1, mon1, yyyy1 = int(m_period.group(1)), m_period.group(2), int(m_period.group(3))
        dd2, mon2, yyyy2 = int(m_period.group(4)), m_period.group(5), int(m_period.group(6))
        mm1 = _parse_month_full(mon1)
        mm2 = _parse_month_full(mon2)
        if mm1 and mm2:
            try:
                period_start = date(yyyy1, mm1, dd1)
            except ValueError:
                period_start = None
            try:
                period_end = date(yyyy2, mm2, dd2)
            except ValueError:
                period_end = None

    opening = _extract_summary_value(raw_text, "saldo inicial")
    closing = _extract_summary_value(raw_text, "saldo final do periodo")
    if closing is None:
        closing = _extract_summary_value(raw_text, "saldo final do período")

    statement_date: date | None = period_end

    txs: list[ParsedTx] = []

    current_date: date | None = None
    current_section: str | None = None  # DEBIT/CREDIT
    pending_parts: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_parts
        pending_parts = []

    for raw_ln in normalized.split("\n"):
        line = (raw_ln or "").strip()
        if not line:
            continue

        low = _strip_accents(line).lower()

        if _is_noise_line(line):
            continue

        # Date header (daily)
        m_day = _DAY_RE.match(line)
        if m_day:
            dd = int(m_day.group(1))
            mm = _parse_month_abbr(m_day.group(2))
            yyyy = int(m_day.group(3))
            if mm:
                try:
                    current_date = date(yyyy, mm, dd)
                    statement_date = current_date if statement_date is None else statement_date
                except ValueError:
                    current_date = None

            # Some PDFs glue "<DD> <MON> <YYYY> Total de entradas/saídas ..." in the same line.
            # Parse the remainder as a normal line so we don't lose section context.
            remainder = line[m_day.end() :].strip()
            current_section = None
            flush_pending()
            if not remainder:
                continue

            low = _strip_accents(remainder).lower().strip()
            if low.startswith("total de entradas"):
                current_section = "CREDIT"
                continue
            if low.startswith("total de saidas") or low.startswith("total de saídas"):
                current_section = "DEBIT"
                continue

            # If remainder isn't a total line, keep processing it as a normal content line.
            line = remainder
            low = _strip_accents(line).lower()

        # Ignore remaining global headers
        if "valores em r$" in low:
            continue

        # Section totals (sets debit/credit context)
        if low.startswith("total de entradas"):
            current_section = "CREDIT"
            flush_pending()
            continue
        if low.startswith("total de saidas") or low.startswith("total de saídas"):
            current_section = "DEBIT"
            flush_pending()
            continue

        # Summary area lines: skip
        if low.startswith("saldo inicial") or low.startswith("saldo final") or low.startswith("rendimento"):
            continue

        if current_date is None:
            # Not in transactions section yet
            continue

        amount, _sign, amount_start = _last_money_at_end(line)
        if amount is None:
            # Collect additional context lines (merchant/bank details)
            # Keep it short to avoid huge descriptions.
            if len(pending_parts) < 3:
                # Avoid collecting pure account-number / agency noise lines
                if not _is_noise_line(line):
                    pending_parts.append(line)
            continue

        desc_part = line[:amount_start].strip() if amount_start is not None else line
        desc = " ".join([p for p in pending_parts + ([desc_part] if desc_part else []) if p]).strip()
        desc = re.sub(r"\s+", " ", desc)

        if not desc:
            desc = "Movimentação"

        # Determine sign (ignore stray '-' used as separator in descriptions)
        abs_amount = amount.copy_abs()
        signed = _infer_signed_amount(abs_amount, current_section, desc)

        tx_type = "DEBIT" if signed < 0 else "CREDIT"

        compact = _compact_description(desc)
        if compact:
            desc = compact

        txs.append(
            ParsedTx(
                transactionDate=current_date,
                description=desc,
                amount=signed,
                balance=None,
                type=tx_type,
            )
        )
        flush_pending()

    if statement_date is None:
        # Fallback: try last explicit yyyy date header in text
        all_days = list(_DAY_RE.finditer(normalized))
        if all_days:
            last = all_days[-1]
            dd = int(last.group(1))
            mm = _parse_month_abbr(last.group(2))
            yyyy = int(last.group(3))
            if mm:
                try:
                    statement_date = date(yyyy, mm, dd)
                except ValueError:
                    statement_date = None

    if opening is None:
        opening = Decimal("0.00")
        warnings.append("missing_opening_balance")

    if closing is None:
        closing = Decimal("0.00")
        warnings.append("missing_closing_balance")

    debug.update(
        {
            "periodStart": period_start.isoformat() if period_start else None,
            "periodEnd": period_end.isoformat() if period_end else None,
            "statementDate": statement_date.isoformat() if statement_date else None,
            "txCount": len(txs),
        }
    )

    result: dict[str, Any] = {
        "bank": "NUBANK",
        "statementDate": (statement_date or date.today()).isoformat(),
        "openingBalance": float(opening.quantize(Decimal("0.01"))),
        "closingBalance": float(closing.quantize(Decimal("0.01"))),
        "transactions": [
            {
                "transactionDate": t.transactionDate.isoformat(),
                "description": t.description,
                "amount": float(t.amount.quantize(Decimal("0.01"))),
                "balance": None,
                "type": t.type,
            }
            for t in txs
        ],
    }

    if not result["transactions"]:
        result["reason"] = "UNSUPPORTED_LAYOUT"

    return result, warnings, debug
