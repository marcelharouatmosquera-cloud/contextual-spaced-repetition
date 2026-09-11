"""Small, corruption-safe JSON state files used by the add-on."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from .debug_log import append_debug_log


class StateFileError(RuntimeError):
    """Raised when invalid state cannot be preserved safely."""


def read_json_state(path: Path, mapping_key: str) -> Dict[str, Any]:
    """Read an object containing ``mapping_key``, quarantining invalid data."""
    empty = {"version": 1, mapping_key: {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get(mapping_key), dict):
            raise ValueError("expected an object containing a %r object" % mapping_key)
        return payload
    except FileNotFoundError:
        return empty
    except Exception as exc:
        backup = _quarantine_invalid_file(path)
        append_debug_log(
            "state_file_quarantined",
            path=str(path),
            backup_path=str(backup),
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return empty


def write_json_state(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically replace a JSON state file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name("%s.tmp" % path.name)
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _quarantine_invalid_file(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name("%s.corrupt-%s" % (path.name, stamp))
    counter = 1
    while backup.exists():
        backup = path.with_name("%s.corrupt-%s-%s" % (path.name, stamp, counter))
        counter += 1
    try:
        path.replace(backup)
    except Exception as exc:
        raise StateFileError(
            "Invalid state file could not be preserved before replacement: %s" % path
        ) from exc
    return backup
