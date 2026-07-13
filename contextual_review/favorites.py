"""Persistent sentence favorites stored separately from the corpus database."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List

from .config import addon_user_root
from .language_profiles import normalize_language_code


FAVORITES_PATH = Path("user_files") / "favorite_sentences.json"


def favorite_sentences(
    database_path: Path | None = None,
    language: str = "",
) -> List[Dict[str, Any]]:
    payload = _read_payload()
    values = [item for item in payload.get("favorites", {}).values() if isinstance(item, dict)]
    if database_path is not None:
        expected_path = str(Path(database_path).expanduser().resolve()).casefold()
        values = [
            item
            for item in values
            if str(item.get("database_path", "") or "").casefold() == expected_path
        ]
    if language:
        expected_language = normalize_language_code(language)
        values = [
            item
            for item in values
            if normalize_language_code(str(item.get("language", "") or ""))
            == expected_language
        ]
    return sorted(values, key=lambda item: float(item.get("saved_at", 0) or 0), reverse=True)


def is_favorite_sentence(database_path: Path, sentence_id: int) -> bool:
    return _favorite_key(database_path, sentence_id) in _read_payload().get("favorites", {})


def toggle_favorite_sentence(database_path: Path, task: Any) -> bool:
    payload = _read_payload()
    favorites = payload.setdefault("favorites", {})
    key = _favorite_key(database_path, int(task.sentence_id))
    if key in favorites:
        del favorites[key]
        _write_payload(payload)
        return False

    favorites[key] = {
        "key": key,
        "sentence_id": int(task.sentence_id),
        "database_path": str(Path(database_path).expanduser().resolve()),
        "language": str(getattr(task, "language", "") or ""),
        "text": str(getattr(task, "full_text", "") or ""),
        "translation": str(getattr(task, "translation", "") or ""),
        "target_words": [
            {
                "word": str(getattr(item, "target_word", "") or ""),
                "definition": str(getattr(item, "definition", "") or ""),
            }
            for item in (getattr(task, "target_words", ()) or ())
        ],
        "saved_at": time.time(),
    }
    _write_payload(payload)
    return True


def remove_favorite_sentence(key: str) -> bool:
    payload = _read_payload()
    favorites = payload.setdefault("favorites", {})
    if str(key or "") not in favorites:
        return False
    del favorites[str(key)]
    _write_payload(payload)
    return True


def _favorite_key(database_path: Path, sentence_id: int) -> str:
    identity = "%s\0%s" % (Path(database_path).expanduser().resolve(), int(sentence_id))
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _favorites_file() -> Path:
    return (addon_user_root() / FAVORITES_PATH).resolve()


def _read_payload() -> Dict[str, Any]:
    path = _favorites_file()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "favorites": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("favorites"), dict):
        return {"version": 1, "favorites": {}}
    return payload


def _write_payload(payload: Dict[str, Any]) -> None:
    path = _favorites_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
