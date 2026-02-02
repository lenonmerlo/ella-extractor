"""Compatibility entrypoint.

Keep this file small.

- `uvicorn app:app ...` continues to work.
- Tests that do `from app import app` continue to work.
"""

from ella_extractor.main import app
