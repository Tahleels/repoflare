"""Converting service.py's result types into plain JSON-serializable structures.

Lives at the package root rather than inside rpc/ because the HTTP API needs the *same*
encoding the VS Code extension receives: if one interface layer turned a `Path` or an `Enum`
into something the other didn't, that is a silent contract break for consumers, not a
cosmetic difference. Extracted from rpc/server.py when api/ arrived.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


def to_jsonable(value: Any) -> Any:
    """Recursively convert dataclasses/Path/Enum/datetime values from service.py's result
    types into plain JSON-serializable structures."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: to_jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, datetime):
        # GovernanceReport.generated_at and friends: isoformat() matches what the
        # extension's TS interfaces declare (generated_at: string).
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: to_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_jsonable(v) for v in value]
    return value
