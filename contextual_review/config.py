"""Configuration loading for the add-on."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .language_profiles import normalize_language_code, profile_dictionary_url


DEFAULT_CUSTOM_SEARCH_QUERY = "is:due -card:2 -card:3 -card:Reverse"
DEFAULT_DATABASE_PATH = "user_files/contextual_sentences.db"
LEGACY_DATABASE_PATH = "data/contextual_sentences.db"
USER_ROOT_ENV = "CONTEXTUAL_REVIEW_USER_ROOT"
DECK_CONFIGS_KEY = "deck_configs"
DECK_CONFIG_META_KEYS = {
    "deck",
    "decks",
    "deck_names",
    "enabled",
    "match",
    "name",
    "profile_name",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "deck_scope": "current",
    "custom_search_query": DEFAULT_CUSTOM_SEARCH_QUERY,
    "deck_name": "",
    "target_field": "Front",
    "dictionary_field": "Back",
    "solution_fields": [{"field": "Back", "label": "", "display": "auto", "autoplay": False}],
    "note_types": [],
    "included_card_templates": [],
    "language": "en",
    "native_language": "en",
    "database_path": DEFAULT_DATABASE_PATH,
    "max_due_cards": 20,
    "max_imported_sentences": 100000,
    "min_sentence_words": 4,
    "max_sentence_words": 15,
    "candidate_limit": 50,
    "query_term_limit": 40,
    "future_due_days": 0,
    "matching_mode": "lemma_family",
    "target_extraction_mode": "content_words",
    "ignored_target_words": [],
    "require_target_on_question": True,
    "include_due_cards": True,
    "include_new_cards": False,
    "max_new_cards": 10,
    "include_learning_cards": True,
    "strict_import_filter": True,
    "keep_downloaded_archives": False,
    "dictionary_url_template": "",
    "known_ease": 3,
    "unknown_ease": 1,
    "font_size": 34,
    DECK_CONFIGS_KEY: [],
}


@dataclass(frozen=True)
class SolutionFieldConfig:
    field: str
    label: str = ""
    display: str = "auto"
    autoplay: bool = False


@dataclass(frozen=True)
class ContextConfig:
    profile_name: str
    active_deck_name: str
    deck_scope: str
    custom_search_query: str
    deck_name: str
    target_field: str
    dictionary_field: str
    solution_fields: List[SolutionFieldConfig]
    note_types: List[str]
    included_card_templates: List[str]
    language: str
    native_language: str
    database_path: str
    max_due_cards: int
    max_imported_sentences: int
    min_sentence_words: int
    max_sentence_words: int
    candidate_limit: int
    query_term_limit: int
    future_due_days: int
    matching_mode: str
    target_extraction_mode: str
    ignored_target_words: List[str]
    require_target_on_question: bool
    include_due_cards: bool
    include_new_cards: bool
    max_new_cards: int
    include_learning_cards: bool
    strict_import_filter: bool
    keep_downloaded_archives: bool
    dictionary_url_template: str
    known_ease: int
    unknown_ease: int
    font_size: int


def addon_root() -> Path:
    return Path(__file__).resolve().parent.parent


def addon_user_root() -> Path:
    configured = os.environ.get(USER_ROOT_ENV)
    if configured:
        return Path(configured).expanduser()
    return addon_root()


def load_config(mw: Optional[Any], addon_name: str, deck_name: Optional[str] = None) -> ContextConfig:
    raw = dict(DEFAULT_CONFIG)
    addon_config: Dict[str, Any] = {}
    if mw is not None:
        try:
            addon_config = mw.addonManager.getConfig(addon_name) or {}
            raw.update(addon_config)
            if "custom_search_query" not in addon_config and "search_query" in addon_config:
                raw["custom_search_query"] = addon_config["search_query"]
            if "solution_fields" not in addon_config:
                raw["solution_fields"] = []
        except Exception:
            pass

    raw = apply_active_deck_config(raw, mw, deck_name=deck_name)
    config = normalize_config(raw)
    if mw is not None and _database_path_key(addon_config.get("database_path")) == LEGACY_DATABASE_PATH:
        _migrate_legacy_default_database()
        _write_migrated_database_config(mw, addon_name, addon_config)
    return config


def normalize_config(raw: Dict[str, Any]) -> ContextConfig:
    note_types = _text_list(raw.get("note_types"))
    language = normalize_language_code(str(raw.get("language", "en") or "en"))
    dictionary_url_template = str(raw.get("dictionary_url_template", "") or "").strip()
    if not dictionary_url_template:
        dictionary_url_template = profile_dictionary_url(language)
    min_sentence_words = _positive_int(raw.get("min_sentence_words"), 4)
    max_sentence_words = _positive_int(raw.get("max_sentence_words"), 15)
    if min_sentence_words > max_sentence_words:
        min_sentence_words, max_sentence_words = max_sentence_words, min_sentence_words
    dictionary_field = str(raw.get("dictionary_field", "Back") or "Back").strip() or "Back"
    raw_solution_fields = raw.get("solution_fields")
    if dictionary_field.casefold() != "back" and _default_back_solution_fields(raw_solution_fields):
        raw_solution_fields = []
    solution_fields = _solution_fields(raw_solution_fields, dictionary_field)

    return ContextConfig(
        profile_name=str(raw.get("_active_profile_name", "") or ""),
        active_deck_name=str(raw.get("_active_deck_name", "") or ""),
        deck_scope=_choice(raw.get("deck_scope"), "current", {"current", "configured", "all"}),
        custom_search_query=_custom_search_query(raw),
        deck_name=str(raw.get("deck_name", "") or "").strip(),
        target_field=str(raw.get("target_field", "Front") or "Front").strip() or "Front",
        dictionary_field=dictionary_field,
        solution_fields=solution_fields,
        note_types=[str(item) for item in note_types if str(item).strip()],
        included_card_templates=_text_list(raw.get("included_card_templates")),
        language=language,
        native_language=normalize_language_code(str(raw.get("native_language", "en") or "en")),
        database_path=_normalized_database_path(raw.get("database_path", DEFAULT_DATABASE_PATH)),
        max_due_cards=_positive_int(raw.get("max_due_cards"), 20),
        max_imported_sentences=max(0, _int(raw.get("max_imported_sentences"), 100000)),
        min_sentence_words=min_sentence_words,
        max_sentence_words=max_sentence_words,
        candidate_limit=_positive_int(raw.get("candidate_limit"), 50),
        query_term_limit=_positive_int(raw.get("query_term_limit"), 40),
        future_due_days=max(0, _int(raw.get("future_due_days"), 0)),
        matching_mode=_choice(raw.get("matching_mode"), "lemma_family", {"lemma_family", "exact_form"}),
        target_extraction_mode=_choice(
            raw.get("target_extraction_mode"),
            "content_words",
            {"content_words", "all_words", "first_word"},
        ),
        ignored_target_words=_word_list(raw.get("ignored_target_words")),
        require_target_on_question=_bool(raw.get("require_target_on_question"), True),
        include_due_cards=_bool(raw.get("include_due_cards"), True),
        include_new_cards=_bool(raw.get("include_new_cards"), False),
        max_new_cards=_positive_int(raw.get("max_new_cards"), 10),
        include_learning_cards=_bool(raw.get("include_learning_cards"), True),
        strict_import_filter=_bool(raw.get("strict_import_filter"), True),
        keep_downloaded_archives=_bool(raw.get("keep_downloaded_archives"), False),
        dictionary_url_template=dictionary_url_template,
        known_ease=_ease(raw.get("known_ease"), 3),
        unknown_ease=_ease(raw.get("unknown_ease"), 1),
        font_size=min(max(_positive_int(raw.get("font_size"), 34), 18), 72),
    )


def apply_active_deck_config(
    raw: Dict[str, Any],
    mw: Optional[Any] = None,
    deck_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge the matching deck profile into the flat config, if one exists."""
    merged = dict(raw)
    active_deck = str(deck_name or active_deck_name(mw, raw) or "").strip()
    if active_deck:
        merged["_active_deck_name"] = active_deck

    profile = find_deck_config(raw, active_deck)
    if not profile:
        return merged

    overrides = deck_config_overrides(profile)
    language_overridden = "language" in overrides
    dictionary_overridden = "dictionary_url_template" in overrides
    merged.update(overrides)
    if language_overridden and not dictionary_overridden:
        merged["dictionary_url_template"] = ""
    merged["_active_profile_name"] = deck_config_name(profile, active_deck)
    return merged


def active_deck_name(mw: Optional[Any], raw: Optional[Dict[str, Any]] = None) -> str:
    raw = raw or {}
    if str(raw.get("deck_scope", "") or "").strip() == "configured":
        configured = str(raw.get("deck_name", "") or "").strip()
        if configured:
            return configured
    return selected_deck_name(mw)


def selected_deck_name(mw: Optional[Any]) -> str:
    if mw is None:
        return ""
    try:
        deck = mw.col.decks.get(mw.col.decks.selected())
        return str(deck.get("name", "") or "").strip()
    except Exception:
        return ""


def find_deck_config(raw: Dict[str, Any], deck_name: str) -> Optional[Dict[str, Any]]:
    deck_name = str(deck_name or "").strip()
    if not deck_name:
        return None
    best_profile: Optional[Dict[str, Any]] = None
    best_score = -1
    for profile in _deck_config_profiles(raw.get(DECK_CONFIGS_KEY)):
        if not _bool(profile.get("enabled", True), True):
            continue
        score = _profile_match_score(profile, deck_name)
        if score > best_score:
            best_profile = profile
            best_score = score
    return best_profile


def upsert_deck_config(raw: Dict[str, Any], deck_name: str, settings: Dict[str, Any]) -> Dict[str, Any]:
    deck_name = str(deck_name or "").strip()
    updated = dict(raw)
    profiles = [dict(profile) for profile in _deck_config_profiles(raw.get(DECK_CONFIGS_KEY))]
    new_profile = dict(settings)
    new_profile["deck_name"] = deck_name
    if not str(new_profile.get("name", "") or "").strip():
        new_profile["name"] = deck_name

    replaced = False
    for index, profile in enumerate(profiles):
        if _profile_has_exact_deck_name(profile, deck_name):
            profiles[index] = new_profile
            replaced = True
            break
    if not replaced:
        profiles.append(new_profile)
    updated[DECK_CONFIGS_KEY] = profiles
    return updated


def deck_config_name(profile: Dict[str, Any], deck_name: str = "") -> str:
    name = str(profile.get("name", "") or profile.get("profile_name", "") or "").strip()
    return name or str(profile.get("deck_name", "") or deck_name or "").strip()


def deck_config_overrides(profile: Dict[str, Any]) -> Dict[str, Any]:
    ignored = set(DECK_CONFIG_META_KEYS)
    return {key: value for key, value in profile.items() if key not in ignored}


def resolve_database_path(config: ContextConfig) -> Path:
    path = Path(config.database_path).expanduser()
    if path.is_absolute():
        return path

    root = addon_user_root().resolve()
    resolved = (root / path).resolve()
    if not _is_relative_to(resolved, root):
        raise ValueError(
            "Relative database paths must stay inside the add-on folder. "
            "Use an absolute path if you want to store the corpus elsewhere."
    )
    return resolved


def _deck_config_profiles(value: Any) -> List[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    profiles: List[Dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            profiles.append(dict(item))
    return profiles


def _profile_match_score(profile: Dict[str, Any], deck_name: str) -> int:
    deck_names = _profile_deck_names(profile)
    if not deck_names:
        return -1
    match_mode = str(profile.get("match", "subdeck") or "subdeck").strip().lower()
    scores = [_deck_name_match_score(candidate, deck_name, match_mode) for candidate in deck_names]
    return max(scores) if scores else -1


def _profile_deck_names(profile: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    for key in ("deck_name", "deck", "deck_names", "decks"):
        value = profile.get(key)
        if isinstance(value, list):
            names.extend(str(item).strip() for item in value if str(item).strip())
        elif value is not None:
            cleaned = str(value).strip()
            if cleaned:
                names.append(cleaned)
    deduped: List[str] = []
    seen = set()
    for name in names:
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            deduped.append(name)
    return deduped


def _profile_has_exact_deck_name(profile: Dict[str, Any], deck_name: str) -> bool:
    deck_key = str(deck_name or "").strip().casefold()
    return any(name.casefold() == deck_key for name in _profile_deck_names(profile))


def _deck_name_match_score(candidate: str, deck_name: str, match_mode: str) -> int:
    candidate = str(candidate or "").strip()
    deck_name = str(deck_name or "").strip()
    if not candidate or not deck_name:
        return -1
    candidate_key = candidate.casefold()
    deck_key = deck_name.casefold()
    if match_mode == "exact":
        return 10000 + len(candidate_key) if deck_key == candidate_key else -1
    if match_mode == "prefix":
        return 5000 + len(candidate_key) if deck_key.startswith(candidate_key) else -1
    if match_mode == "contains":
        return 1000 + len(candidate_key) if candidate_key in deck_key else -1
    if match_mode == "regex":
        try:
            return 100 if re.search(candidate, deck_name, re.IGNORECASE) is not None else -1
        except re.error:
            return -1
    if deck_key == candidate_key:
        return 10000 + len(candidate_key)
    if deck_key.startswith(candidate_key + "::"):
        return 7000 + len(candidate_key)
    return -1


def _positive_int(value: Any, default: int) -> int:
    parsed = _int(value, default)
    return parsed if parsed > 0 else default


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _ease(value: Any, default: int) -> int:
    parsed = _positive_int(value, default)
    return min(max(parsed, 1), 4)


def _bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return default
    if value is None:
        return default
    return bool(value)


def _choice(value: Any, default: str, allowed: set[str]) -> str:
    parsed = str(value or default).strip().lower()
    return parsed if parsed in allowed else default


def _word_list(value: Any) -> List[str]:
    return _split_list(value, r"[\s,;]+")


def _text_list(value: Any) -> List[str]:
    return _split_list(value, r"[,;\n]+")


def _solution_fields(value: Any, dictionary_field: str) -> List[SolutionFieldConfig]:
    rows: List[SolutionFieldConfig] = []
    if isinstance(value, str):
        value = [{"field": item} for item in _text_list(value)]
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str):
                field_name = item.strip()
                label = ""
                display = "auto"
                autoplay = False
            elif isinstance(item, dict):
                field_name = str(item.get("field", "") or "").strip()
                label = str(item.get("label", "") or "").strip()
                display = _choice(
                    item.get("display"),
                    "auto",
                    {"auto", "text", "image", "audio"},
                )
                autoplay = _bool(item.get("autoplay"), False)
            else:
                continue
            if not field_name:
                continue
            rows.append(
                SolutionFieldConfig(
                    field=field_name,
                    label=label,
                    display=display,
                    autoplay=autoplay,
                )
            )
    if not rows:
        rows.append(SolutionFieldConfig(field=dictionary_field))
    return rows


def _default_back_solution_fields(value: Any) -> bool:
    if not isinstance(value, list) or len(value) != 1:
        return False
    item = value[0]
    if isinstance(item, str):
        return item.strip().casefold() == "back"
    if not isinstance(item, dict):
        return False
    return (
        str(item.get("field", "") or "").strip().casefold() == "back"
        and not str(item.get("label", "") or "").strip()
        and str(item.get("display", "auto") or "auto").strip().lower() == "auto"
        and not _bool(item.get("autoplay"), False)
    )


def _split_list(value: Any, pattern: str) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if item is not None and str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in re.split(pattern, value.strip()) if item.strip()]
    return []


def _custom_search_query(raw: Dict[str, Any]) -> str:
    if "custom_search_query" in raw:
        query = str(raw.get("custom_search_query") or "").strip()
        return query or DEFAULT_CUSTOM_SEARCH_QUERY
    if "search_query" in raw:
        query = str(raw.get("search_query") or "").strip()
        return query or DEFAULT_CUSTOM_SEARCH_QUERY
    return DEFAULT_CUSTOM_SEARCH_QUERY


def _normalized_database_path(value: Any) -> str:
    path = str(value or DEFAULT_DATABASE_PATH).strip() or DEFAULT_DATABASE_PATH
    if _database_path_key(path) == LEGACY_DATABASE_PATH:
        return DEFAULT_DATABASE_PATH
    return path


def _database_path_key(value: Any) -> str:
    return str(value or "").strip().replace("\\", "/").lower()


def _migrate_legacy_default_database() -> bool:
    root = addon_user_root()
    legacy_path = root / LEGACY_DATABASE_PATH
    target_path = root / DEFAULT_DATABASE_PATH
    if target_path.exists() or not legacy_path.exists():
        return False
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(legacy_path, target_path)
    return True


def _write_migrated_database_config(mw: Any, addon_name: str, addon_config: Dict[str, Any]) -> None:
    write_config = getattr(getattr(mw, "addonManager", None), "writeConfig", None)
    if not callable(write_config):
        return
    migrated = dict(addon_config)
    migrated["database_path"] = DEFAULT_DATABASE_PATH
    try:
        write_config(addon_name, migrated)
    except Exception:
        pass


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
