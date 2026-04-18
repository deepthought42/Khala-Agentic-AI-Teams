"""Small YAML-backed table loader shared by bmr/tdee/macros/micros.

Modules call ``load_table(name)`` once at import (module-level
constant) so per-call cost is zero. The loader is private
(``_tables``) because the individual tables are the public contract,
not the loader.

The loader is defensive: raises at import time if any table file is
missing, malformed, or returns a non-dict top-level value. That is
the desired failure mode — a deployed calculator must have all of
its tables present.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_TABLES_DIR = Path(__file__).resolve().parent / "tables"


@lru_cache(maxsize=None)
def load_table(name: str) -> dict[str, Any]:
    """Load a YAML table by basename (without .yaml extension)."""
    path = _TABLES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"nutrition_calc table missing: {path}")
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"nutrition_calc table {name}.yaml must be a mapping")
    return data
