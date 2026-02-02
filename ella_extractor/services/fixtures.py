from __future__ import annotations

from pathlib import Path


def write_text_fixture(*, filename: str, raw_text: str, base_dir: Path) -> Path:
    """Write raw_text fixture under tests/fixtures.

    Keeps behavior identical to the previous inline implementation: always overwrites.
    """

    fixture_path = base_dir / "tests" / "fixtures" / filename
    fixture_path.parent.mkdir(parents=True, exist_ok=True)
    fixture_path.write_text(raw_text, encoding="utf-8")
    return fixture_path
