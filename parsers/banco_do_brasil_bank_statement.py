from __future__ import annotations

# Backwards compatible import location.
# Canonical implementation lives in `parsers.statements.banco_do_brasil_bank_statement`.

from parsers.statements.banco_do_brasil_bank_statement import (  # noqa: F401
    looks_like_banco_do_brasil_bank_statement,
    parse_banco_do_brasil_bank_statement,
)
