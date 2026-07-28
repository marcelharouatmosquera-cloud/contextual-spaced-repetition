"""Runtime diagnostics for settings, corpus, and scheduler readiness."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .anki_bridge import (
    build_due_search_query,
    card_question_contains_target_field,
    card_review_direction,
    card_template_labels,
    note_field_names,
)
from .config import ContextConfig, load_config, resolve_database_path
from .corpus import open_review_database
from .debug_log import debug_log_path
from .language_profiles import language_match_codes
from .normalizer import is_unsegmented_language


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class DiagnosticReport:
    checks: List[DiagnosticCheck]

    @property
    def ok(self) -> bool:
        return not any(check.status == "error" for check in self.checks)

    @property
    def has_warnings(self) -> bool:
        return any(check.status == "warning" for check in self.checks)

    @property
    def needs_attention(self) -> bool:
        return not self.ok or self.has_warnings


def collect_diagnostics(mw: Any, addon_name: str) -> DiagnosticReport:
    config = load_config(mw, addon_name)
    try:
        database_check = _database_check(resolve_database_path(config), config.language)
    except Exception as exc:
        database_check = DiagnosticCheck("Corpus database", "error", "invalid path: %s" % exc)
    checks = [
        _config_check(config),
        database_check,
        _scheduler_check(mw),
        _native_undo_check(mw),
        _background_task_check(mw),
        _debug_log_check(),
        _due_search_check(mw, config),
        _field_configuration_check(mw, config),
        _card_direction_check(mw, config),
    ]
    return DiagnosticReport(checks)


def format_diagnostics(report: DiagnosticReport) -> str:
    lines = ["Contextual Review diagnostics", ""]
    for check in report.checks:
        marker = {"ok": "OK", "warning": "WARN", "error": "ERROR"}.get(check.status, check.status.upper())
        lines.append("[%s] %s: %s" % (marker, check.name, check.detail))
    return "\n".join(lines)


def _config_check(config: ContextConfig) -> DiagnosticCheck:
    issues = []
    if config.min_sentence_words > config.max_sentence_words:
        issues.append("min sentence words exceeds max")
    if config.known_ease == config.unknown_ease:
        issues.append("known and unknown ease are identical")
    if config.deck_scope == "configured" and not config.deck_name.strip():
        issues.append("configured deck scope has no deck name")
    if config.target_field.strip().casefold() == config.dictionary_field.strip().casefold():
        issues.append("target and translation fields are identical")
    if issues:
        return DiagnosticCheck("Config", "warning", "; ".join(issues))
    profile = "global"
    if config.profile_name:
        profile = "%s for %s" % (config.profile_name, config.active_deck_name or "active deck")
    return DiagnosticCheck(
        "Config",
        "ok",
        "profile=%s, language=%s, field=%s, matching=%s"
        % (profile, config.language, config.target_field, config.matching_mode),
    )


def _database_check(path: Path, language: str) -> DiagnosticCheck:
    if not path.exists():
        return DiagnosticCheck("Corpus database", "error", "missing at %s" % path)
    if not _sqlite_has_fts5():
        return DiagnosticCheck("Corpus database", "error", "SQLite FTS5 is not available")

    try:
        conn = open_review_database(path)
        try:
            tables = _table_names(conn)
            missing = sorted({"sentences", "sentence_forms", "word_forms"} - tables)
            if missing:
                return DiagnosticCheck("Corpus database", "error", "missing table(s): %s" % ", ".join(missing))
            total = int(conn.execute("SELECT COUNT(*) FROM sentences").fetchone()[0])
            sentence_forms_count = int(
                conn.execute("SELECT COUNT(*) FROM sentence_forms").fetchone()[0]
            )
            language_codes = language_match_codes(language)
            placeholders = ", ".join("?" for _ in language_codes)
            language_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM sentences WHERE language IN (%s)" % placeholders,
                    language_codes,
                ).fetchone()[0]
            )
            translated_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM sentences WHERE language IN (%s) AND COALESCE(translation, '') != ?"
                    % placeholders,
                    [*language_codes, ""],
                ).fetchone()[0]
            )
            word_forms_count = int(conn.execute("SELECT COUNT(*) FROM word_forms").fetchone()[0])
            cjk_fts_present = "fts_cjk" in tables
            cjk_fts_count = (
                int(
                    conn.execute(
                        "SELECT COUNT(*) FROM fts_cjk "
                        "JOIN sentences s ON s.id = fts_cjk.rowid "
                        "WHERE s.language IN (%s)" % placeholders,
                        language_codes,
                    ).fetchone()[0]
                )
                if cjk_fts_present
                else 0
            )
        finally:
            conn.close()
    except Exception as exc:
        return DiagnosticCheck("Corpus database", "error", str(exc))

    if total == 0:
        return DiagnosticCheck("Corpus database", "warning", "database has no sentences")
    if language_count == 0:
        return DiagnosticCheck(
            "Corpus database",
            "warning",
            "%s sentences total, but none for language %s" % (total, language),
        )
    if sentence_forms_count != total:
        return DiagnosticCheck(
            "Corpus database",
            "warning",
            "%s sentences but %s form-index rows; import content again to repair the index"
            % (total, sentence_forms_count),
        )
    if is_unsegmented_language(language) and not cjk_fts_present:
        return DiagnosticCheck(
            "Corpus database",
            "warning",
            "%s sentences for language %s, but the FTS5 trigram index is missing; start review once or import content to migrate it"
            % (language_count, language),
        )
    if is_unsegmented_language(language) and language_count and not cjk_fts_count:
        return DiagnosticCheck(
            "Corpus database",
            "warning",
            "%s sentences for language %s, but the FTS5 trigram index is empty; import content again to repair it"
            % (language_count, language),
        )
    return DiagnosticCheck(
        "Corpus database",
        "ok",
        "%s sentences total; %s for language %s; %s translated; %s word-form mappings; %s trigram-index rows for this language"
        % (total, language_count, language, translated_count, word_forms_count, cjk_fts_count),
    )


def _scheduler_check(mw: Any) -> DiagnosticCheck:
    collection = getattr(mw, "col", None)
    scheduler = getattr(collection, "sched", None)
    if scheduler is None:
        return DiagnosticCheck("Scheduler", "error", "collection scheduler unavailable")
    grade_now = getattr(getattr(collection, "_backend", None), "grade_now", None)
    if callable(grade_now):
        return DiagnosticCheck("Scheduler", "ok", "native grade_now batch API available")
    return DiagnosticCheck("Scheduler", "error", "backend grade_now API unavailable")


def _native_undo_check(mw: Any) -> DiagnosticCheck:
    collection = getattr(mw, "col", None)
    required = {
        "add_custom_undo_entry": getattr(collection, "add_custom_undo_entry", None),
        "merge_undo_entries": getattr(collection, "merge_undo_entries", None),
        "undo": getattr(collection, "undo", None),
    }
    missing = [name for name, value in required.items() if not callable(value)]
    if missing:
        return DiagnosticCheck(
            "Undo support",
            "error",
            "native batch undo API(s) unavailable: %s" % ", ".join(missing),
        )
    if not callable(getattr(collection, "undo_status", None)):
        return DiagnosticCheck(
            "Undo support",
            "warning",
            "native batch undo available; undo_status unavailable for guarded Ctrl+Z",
        )
    return DiagnosticCheck(
        "Undo support",
        "ok",
        "native custom undo merge and guarded Ctrl+Z APIs available",
    )


def _background_task_check(mw: Any) -> DiagnosticCheck:
    taskman = getattr(mw, "taskman", None)
    if taskman and hasattr(taskman, "run_in_background"):
        return DiagnosticCheck("Background imports", "ok", "task manager available")
    return DiagnosticCheck("Background imports", "warning", "imports will run synchronously")


def _debug_log_check() -> DiagnosticCheck:
    path = debug_log_path()
    try:
        if path.exists():
            return DiagnosticCheck("Debug log", "ok", "%s (%s bytes)" % (path, path.stat().st_size))
    except Exception as exc:
        return DiagnosticCheck("Debug log", "warning", "could not inspect log path: %s" % exc)
    return DiagnosticCheck("Debug log", "ok", "will be written to %s after reviews" % path)


def _due_search_check(mw: Any, config: ContextConfig) -> DiagnosticCheck:
    try:
        query = build_due_search_query(mw, config)
        card_ids = list(mw.col.find_cards(query))
    except Exception as exc:
        return DiagnosticCheck("Due search", "warning", "could not run due search: %s" % exc)

    if not card_ids:
        return DiagnosticCheck("Due search", "warning", "query returned no cards: %s" % query)
    return DiagnosticCheck("Due search", "ok", "query returned %s card(s): %s" % (len(card_ids), query))


def _field_configuration_check(mw: Any, config: ContextConfig) -> DiagnosticCheck:
    try:
        query = build_due_search_query(mw, config)
        card_ids = list(mw.col.find_cards(query))[:200]
    except Exception as exc:
        return DiagnosticCheck("Note fields", "warning", "could not inspect fields: %s" % exc)
    if not card_ids:
        return DiagnosticCheck("Note fields", "warning", "no matching cards available to inspect")

    available: Dict[str, str] = {}
    for card_id in card_ids:
        try:
            note = mw.col.get_card(card_id).note()
        except Exception:
            continue
        for field_name in note_field_names(note):
            available.setdefault(field_name.casefold(), field_name)
    if not available:
        return DiagnosticCheck("Note fields", "warning", "could not read note fields")

    target_missing = config.target_field.casefold() not in available
    missing_solution = [
        spec.field for spec in config.solution_fields if spec.field.casefold() not in available
    ]
    if target_missing:
        return DiagnosticCheck(
            "Note fields",
            "error",
            "target field '%s' was not found; available fields: %s"
            % (config.target_field, ", ".join(available.values())),
        )
    configured = ", ".join(spec.field for spec in config.solution_fields)
    if missing_solution:
        return DiagnosticCheck(
            "Note fields",
            "warning",
            "target field found; missing solution field(s): %s; configured solution fields: %s"
            % (", ".join(missing_solution), configured),
        )
    return DiagnosticCheck(
        "Note fields",
        "ok",
        "target=%s; solution fields=%s" % (config.target_field, configured),
    )


def _card_direction_check(mw: Any, config: ContextConfig) -> DiagnosticCheck:
    try:
        query = build_due_search_query(mw, config)
        card_ids = list(mw.col.find_cards(query))[:200]
    except Exception as exc:
        return DiagnosticCheck("Card directions", "warning", "could not inspect cards: %s" % exc)

    if not card_ids:
        return DiagnosticCheck("Card directions", "warning", "no due cards available to inspect")

    recognition_count = 0
    recall_count = 0
    excluded_count = 0
    invalid_recognition_count = 0
    invalid_recall_count = 0
    template_counts: Dict[str, int] = {}
    inspected = 0
    for card_id in card_ids:
        try:
            card = mw.col.get_card(card_id)
            note = card.note()
        except Exception:
            continue
        inspected += 1
        labels = card_template_labels(card, note)
        label = labels[-1] if labels else "Card"
        template_counts[label] = template_counts.get(label, 0) + 1
        direction, template_allowed = card_review_direction(card, note, config)
        if not template_allowed and direction == "recall":
            invalid_recall_count += 1
        elif not template_allowed:
            excluded_count += 1
        elif direction == "recall":
            recall_count += 1
        elif (
            not config.require_target_on_question
            or card_question_contains_target_field(card, note, config.target_field)
        ):
            recognition_count += 1
        else:
            invalid_recognition_count += 1

    if inspected == 0:
        return DiagnosticCheck("Card directions", "warning", "could not load due cards for inspection")

    templates = ", ".join(
        "%s=%s" % (name, count) for name, count in sorted(template_counts.items())
    )
    configured_directions = []
    if config.included_card_templates:
        configured_directions.append(
            "recognition templates=%s" % ", ".join(config.included_card_templates)
        )
    if config.recall_templates:
        configured_directions.append(
            "recall templates=%s" % ", ".join(config.recall_templates)
        )
    configured = "; %s" % "; ".join(configured_directions) if configured_directions else ""
    detail = (
        "sampled %s card(s); recognition=%s; recall=%s; excluded=%s; "
        "invalid recognition=%s; invalid recall=%s; templates: %s%s"
        % (
            inspected,
            recognition_count,
            recall_count,
            excluded_count,
            invalid_recognition_count,
            invalid_recall_count,
            templates or "unknown",
            configured,
        )
    )
    status = "warning" if invalid_recognition_count or invalid_recall_count else "ok"
    return DiagnosticCheck("Card directions", status, detail)


def _sqlite_has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE diag_fts USING fts5(x, tokenize='trigram')")
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    return {str(row[0]) for row in rows}
