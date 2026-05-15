"""CSV loading helpers for test MCP service data."""

from __future__ import annotations

import csv
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


def csv_rows(filename: str) -> list[dict[str, str]]:
    """Load a CSV file from DATA_DIR and return a list of row dicts."""
    path = DATA_DIR / filename
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def csv_table(filename: str, key_col: str) -> dict[str, dict[str, str]]:
    """Load a CSV and return a dict keyed on key_col for O(1) lookup."""
    rows = csv_rows(filename)
    return {row[key_col]: row for row in rows}
