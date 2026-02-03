from __future__ import annotations

# NOTE: This module is kept for backwards compatibility.
# Canonical implementation lives in `parsers.statements.nubank_bank_statement`.

from parsers.statements.nubank_bank_statement import (  # noqa: F401
    looks_like_nubank_bank_statement,
    parse_nubank_bank_statement,
)
