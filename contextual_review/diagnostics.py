"""Runtime diagnostics for settings, corpus, and scheduler readiness."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

from .anki_bridge import (
    build_due_search_query,
    card_question_contains_target_field,
    card_template_labels,
    note_field_names,
)
from .config import ContextConfig, load_config, resolve_database_path
from .corpus import open_review_database
from .debug_log import debug_log_path
from .language_profiles import language_match_codes


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
        _checkpoint_check(mw),
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
    return DiagnosticCheck(
        "Corpus database",
        "ok",
        "%s sentences total; %s for language %s; %s translated; %s word-form mappings"
        % (total, language_count, language, translated_count, word_forms_count),
    )


def _scheduler_check(mw: Any) -> DiagnosticCheck:
    scheduler = getattr(getattr(mw, "col", None), "sched", None)
    if scheduler is None:
        return DiagnosticCheck("Scheduler", "error", "collection scheduler unavailable")
    if hasattr(scheduler, "answerCard") or hasattr(scheduler, "answer_card"):
        return DiagnosticCheck("Scheduler", "ok", "native answer API available")
    return DiagnosticCheck("Scheduler", "error", "answerCard/answer_card unavailable")


def _checkpoint_check(mw: Any) -> DiagnosticCheck:
    if getattr(getattr(mw, "col", None), "db", None) is not None:
        return DiagnosticCheck("Undo support", "ok", "contextual batch snapshots available")
    if callable(getattr(mw, "checkpoint", None)):
        return DiagnosticCheck("Undo support", "ok", "mw.checkpoint available")
    return DiagnosticCheck("Undo support", "error", "mw.checkpoint unavailable")


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

    target_on_question = 0
    likely_reverse = 0
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
        if card_question_contains_target_field(card, note, config.target_field):
            target_on_question += 1
        else:
            likely_reverse += 1

    if inspected == 0:
        return DiagnosticCheck("Card directions", "warning", "could not load due cards for inspection")

    templates = ", ".join(
        "%s=%s" % (name, count) for name, count in sorted(template_counts.items())
    )
    included = (
        "; included templates=%s" % ", ".join(config.included_card_templates)
        if config.included_card_templates
        else ""
    )
    detail = (
        "sampled %s card(s); %s contain target field on question; %s look reverse/production; templates: %s%s"
        % (inspected, target_on_question, likely_reverse, templates or "unknown", included)
    )
    status = "warning" if likely_reverse and not config.included_card_templates else "ok"
    return DiagnosticCheck("Card directions", status, detail)


def _sqlite_has_fts5() -> bool:
    try:
        conn = sqlite3.connect(":memory:")
        try:
            conn.execute("CREATE VIRTUAL TABLE diag_fts USING fts5(x)")
        finally:
            conn.close()
        return True
    except sqlite3.Error:
        return False


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')").fetchall()
    return {str(row[0]) for row in rows}
