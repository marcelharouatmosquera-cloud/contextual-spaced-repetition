"""Language profile loading for per-language defaults."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str = ""
    tatoeba_code: str = ""
    dictionary_url_template: str = ""
    ignored_target_words: List[str] = field(default_factory=list)
    matching_mode: str = ""
    notes: str = ""

def get_language_profile(language: str) -> LanguageProfile:
    profiles = load_language_profiles()
    code = normalize_language_code(language)
    return profiles.get(code) or LanguageProfile(code=code)


@lru_cache(maxsize=4)
def load_language_profiles(path: Optional[Path] = None) -> Dict[str, LanguageProfile]:
    profile_path = path or _default_profile_path()
    try:
        raw = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        raw = {}

    profiles: Dict[str, LanguageProfile] = {}
    for code, data in raw.items():
        if not isinstance(data, dict):
            continue
        profile = LanguageProfile(
            code=_basic_language_code(code),
            name=str(data.get("name", "")),
            tatoeba_code=str(data.get("tatoeba_code", "")),
            dictionary_url_template=str(data.get("dictionary_url_template", "")),
            ignored_target_words=_string_list(data.get("ignored_target_words")),
            matching_mode=str(data.get("matching_mode", "")),
            notes=str(data.get("notes", "")),
        )
        profiles[profile.code] = profile
    return profiles


def normalize_language_code(language: str) -> str:
    code = _basic_language_code(language)
    return _tatoeba_aliases().get(code, code)


def language_match_codes(language: str) -> List[str]:
    code = normalize_language_code(language)
    codes = [code]
    profile = get_language_profile(code)
    if profile.tatoeba_code and profile.tatoeba_code not in codes:
        codes.append(profile.tatoeba_code)
    raw_code = _basic_language_code(language)
    if raw_code not in codes:
        codes.append(raw_code)
    return codes


def profile_ignored_words(language: str) -> List[str]:
    return list(get_language_profile(language).ignored_target_words)


def profile_tatoeba_code(language: str) -> str:
    profile = get_language_profile(language)
    return profile.tatoeba_code or normalize_language_code(language)


def profile_dictionary_url(language: str) -> str:
    profile = get_language_profile(language)
    return profile.dictionary_url_template or "https://en.wiktionary.org/wiki/{word}"


def _default_profile_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "language_profiles.json"


def _basic_language_code(language: str) -> str:
    code = re.split(r"[-_]", str(language or "en").strip(), maxsplit=1)[0]
    return code.lower() or "en"


@lru_cache(maxsize=1)
def _tatoeba_aliases() -> Dict[str, str]:
    aliases: Dict[str, str] = {}
    for code, profile in load_language_profiles().items():
        tatoeba_code = _basic_language_code(profile.tatoeba_code)
        if tatoeba_code and tatoeba_code != code:
            aliases[tatoeba_code] = code
    return aliases


def _string_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        return [item for item in re.split(r"[\s,;]+", value.strip()) if item]
    return []
