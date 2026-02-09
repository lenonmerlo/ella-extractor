from __future__ import annotations

# NOTE: This module is kept for backwards compatibility.
# Canonical implementation lives in `parsers.statements.bradesco_bank_statement`.

from parsers.statements.bradesco_bank_statement import (  # noqa: F401
    looks_like_bradesco_bank_statement,
    parse_bradesco_bank_statement,
)
