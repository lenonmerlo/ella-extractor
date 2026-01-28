from __future__ import annotations

import sys
from pathlib import Path

# Ensure imports like `import app` and `from parsers...` work no matter how pytest is invoked
# (e.g. `pytest` vs `python -m pytest`) and regardless of the current working directory.
_EXTRACTOR_DIR = Path(__file__).resolve().parents[1]
if str(_EXTRACTOR_DIR) not in sys.path:
    sys.path.insert(0, str(_EXTRACTOR_DIR))
