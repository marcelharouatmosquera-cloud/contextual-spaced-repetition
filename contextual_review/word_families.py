"""Read-only, reusable word-family index for existing sentence libraries."""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Dict, FrozenSet

from .language_profiles import language_match_codes, normalize_language_code
from .normalizer import WORD_RE, normalize_form, normalize_word

_CACHE: OrderedDict = OrderedDict()
_LOCK = RLock()
_MAX_CACHED_LANGUAGES = 2


def family_index(conn: sqlite3.Connection, language: str) -> Dict[str, FrozenSet[str]]:
    """Map current stems to the folded surface forms used by the legacy FTS index.

    Stem original sentence spellings, not the lossy word_forms table. French
    chevaux -> cheval and Arabic prefixes also make prefix-only lookup unsafe.
    Cache at most two libraries/languages; file and WAL changes invalidate it.
    In-memory databases and uncommitted writes are deliberately not cached.
    """
    language = normalize_language_code(language)
    key = _cache_key(conn, language)
    with _LOCK:
        if key is not None and key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
        index = _build_index(conn, language)
        if key is not None and key == _cache_key(conn, language):
            _CACHE[key] = index
            while len(_CACHE) > _MAX_CACHED_LANGUAGES:
                _CACHE.popitem(last=False)
        return index


def _cache_key(conn: sqlite3.Connection, language: str):
    path = next((row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"), "")
    if not path or conn.in_transaction:
        return None
    fingerprints = []
    for candidate in (Path(path), Path(path + "-wal")):
        try:
            stat = candidate.stat()
            fingerprints.append((stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns))
        except FileNotFoundError:
            fingerprints.append(None)
    return (str(Path(path).resolve()), language, tuple(fingerprints))


def _build_index(conn: sqlite3.Connection, language: str) -> Dict[str, FrozenSet[str]]:
    codes = language_match_codes(language)
    rows = conn.execute(
        "SELECT full_text FROM sentences WHERE language IN (%s)" % ",".join("?" for _ in codes),
        codes,
    )
    # Collect unique spellings first: a 200k-sentence library has far fewer
    # distinct words than tokens. Only stem each spelling once on a cold load.
    words = {
        match.group(0)
        for row in rows
        for match in WORD_RE.finditer(str(row[0]))
    }
    families: Dict[str, set] = {}
    for word in words:
        stem = normalize_word(word, language)
        if stem:
            families.setdefault(stem, set()).add(normalize_form(word))
    return {stem: frozenset(forms) for stem, forms in families.items()}
