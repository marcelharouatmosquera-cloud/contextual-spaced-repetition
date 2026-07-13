"""Lightweight runtime logging for troubleshooting scheduler behavior."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import addon_user_root

LOG_PATH = Path("user_files") / "contextual_review.log"
MAX_LOG_BYTES = 1_000_000


def debug_log_path() -> Path:
    return addon_user_root() / LOG_PATH


def append_debug_log(event: str, **fields: Any) -> None:
    """Append one JSON line and never let logging break reviews."""
    try:
        path = debug_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(path)
        payload = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": str(event),
        }
        payload.update({str(key): _json_safe(value) for key, value in fields.items()})
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except Exception:
        pass


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size <= MAX_LOG_BYTES:
            return
        rotated = path.with_name("%s.1" % path.name)
        if rotated.exists():
            rotated.unlink()
        path.replace(rotated)
    except Exception:
        pass


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
