"""Dedicated contextual review dialog."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote, unquote, urlsplit

from .anki_bridge import BatchUndoSnapshot, answer_review_task, collect_due_cards, restore_answer_snapshot
from .config import addon_user_root, load_config, resolve_database_path
from .corpus import select_review_task
from .debug_log import append_debug_log
from .types import DueCard, ReviewTask
from .web import render_message_html, render_task_html

RECENT_SENTENCE_HISTORY_PATH = Path("user_files") / "recent_sentence_history.json"
RECENT_SENTENCE_LIMIT = 200


def open_contextual_review_dialog(mw: Any, addon_name: str) -> "ContextualReviewDialog":  # pragma: no cover
    dialog = ContextualReviewDialog(mw, addon_name)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    dialog.start()
    return dialog


class ContextualReviewDialog:  # pragma: no cover - exercised inside Anki
    def __init__(self, mw: Any, addon_name: str) -> None:
        from aqt.qt import QDialog, QVBoxLayout
        from aqt.webview import AnkiWebView

        self._dialog = QDialog(mw)
        self._dialog.setWindowTitle("Contextual Review")
        self._dialog.resize(900, 520)
        setattr(self._dialog, "_contextual_review_controller", self)

        self.mw = mw
        self.addon_name = addon_name
        self.config = load_config(mw, addon_name)
        try:
            from .tts import cleanup_tts_cache

            cleanup_tts_cache()
        except Exception:
            pass
        self.database_path_error = ""
        try:
            self.db_path = resolve_database_path(self.config)
        except Exception as exc:
            self.db_path = Path()
            self.database_path_error = str(exc)
        self.shown_sentence_ids: Set[int] = set()
        self.recent_sentence_ids: Set[int] = (
            set()
            if self.database_path_error
            else _load_recent_sentence_ids(self.db_path, self.config.language)
        )
        self.answered_card_ids: Set[int] = set()
        self.review_history: List[Tuple[ReviewTask, List[int], Optional[BatchUndoSnapshot]]] = []
        self._session_results: List[Tuple[int, int]] = []
        self._session_forgotten_words: List[List[str]] = []
        self._session_summary_shown = False
        # Sentences displaced by Previous are resumed in order after the
        # restored reviews are graded again. They have already been selected
        # and shown, so running corpus selection again would unnecessarily
        # replace them with a different sentence for the same card.
        self._interrupted_tasks: List[ReviewTask] = []
        self.today_goal_card_ids: Set[int] = set()
        self._today_goal_initialized = False
        self.active_task: Optional[ReviewTask] = None
        self._loading = False
        self._started = False
        self._selection_generation = 0
        self._due_cards_cache: Optional[Tuple[DueCard, ...]] = None

        self.web = AnkiWebView()
        self.web.set_bridge_command(self._on_bridge_command, self)
        self._dialog.finished.connect(self._on_dialog_finished)

        layout = QVBoxLayout()
        layout.addWidget(self.web)
        self._dialog.setLayout(layout)
        self._set_html(
            render_message_html(
                "Preparing contextual review",
                "Finding due cards and a useful sentence...",
                dark_mode=self._dark_mode(),
                font_size=self.config.font_size,
                show_refresh=False,
            )
        )

    def show(self) -> None:
        self._dialog.show()

    def raise_(self) -> None:
        self._dialog.raise_()

    def activateWindow(self) -> None:
        self._dialog.activateWindow()

    def start(self) -> None:
        """Begin loading only after the dialog has been made visible."""
        if self._started:
            return
        self._started = True
        self._load_next_task()

    def _load_next_task(self, refresh_due_cards: bool = False) -> None:
        if getattr(self, "_loading", False):
            return
        if getattr(self, "database_path_error", ""):
            self._set_html(
                render_message_html(
                    "Database path needs attention",
                    self.database_path_error,
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Open Settings",
                    action="settings",
                    extra_actions=(("Diagnostics", "diagnostics"),),
                )
            )
            return
        if not self.db_path.exists():
            self._set_html(
                render_message_html(
                    "Sentence database missing",
                    (
                        "No sentence database was found at %s. "
                        "Open Contextual Review Settings and use the Sentence Library section."
                    )
                    % self.db_path,
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Open Settings",
                    action="settings",
                    extra_actions=(("Diagnostics", "diagnostics"),),
                )
            )
            return

        due_started = time.perf_counter()
        cache_hit = not refresh_due_cards and getattr(self, "_due_cards_cache", None) is not None
        try:
            if cache_hit:
                collected_due_cards = list(self._due_cards_cache or ())
            else:
                collected_due_cards = collect_due_cards(self.mw, self.config)
                self._due_cards_cache = tuple(collected_due_cards)
            if not getattr(self, "_today_goal_initialized", False):
                full_today_ids = getattr(collected_due_cards, "today_card_ids", None)
                self.today_goal_card_ids = set(
                    full_today_ids
                    if full_today_ids is not None
                    else (card.card_id for card in collected_due_cards)
                )
                self._today_goal_initialized = True
            # A cached DueCard reflects the card's state before it was graded.
            # Hide every card already reviewed from that cache, including cards
            # answered Again. Once the cache is refreshed, Anki's current due
            # search decides whether a forgotten card's relearning delay has
            # elapsed and it may be shown again.
            cached_reviewed_card_ids = (
                {
                    card_id
                    for _task, card_ids, _snapshot in getattr(self, "review_history", [])
                    for card_id in card_ids
                }
                if cache_hit
                else set()
            )
            hidden_card_ids = set(self.answered_card_ids) | cached_reviewed_card_ids
            due_cards = [
                card for card in collected_due_cards if card.card_id not in hidden_card_ids
            ]
            append_debug_log(
                "review_window_due_filter",
                collected_target_count=len(collected_due_cards),
                returned_target_count=len(due_cards),
                collected_card_ids=sorted({card.card_id for card in collected_due_cards}),
                hidden_known_card_ids=sorted(self.answered_card_ids),
                hidden_cached_reviewed_card_ids=sorted(cached_reviewed_card_ids),
                elapsed_ms=round((time.perf_counter() - due_started) * 1000, 1),
                cache_hit=cache_hit,
            )
        except Exception as exc:
            self._set_html(
                render_message_html(
                    "Could not read due cards",
                    str(exc),
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Diagnostics",
                    action="diagnostics",
                )
            )
            return

        if not due_cards and cache_hit:
            # The cached batch has been exhausted. Refresh once so cards beyond
            # the configured batch limit can enter the session.
            self._due_cards_cache = None
            self._load_next_task()
            return

        if not due_cards:
            self.active_task = None
            summary = self._session_summary_text()
            if summary:
                self._session_summary_shown = True
            self._set_html(
                render_message_html(
                    "Session complete" if summary else "All done",
                    summary
                    or "No due vocabulary cards were found. If this seems wrong, run Diagnostics to check the search filter and card direction settings.",
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Standard Reviews" if summary else "Diagnostics",
                    action="standard_review" if summary else "diagnostics",
                    extra_actions=(("Diagnostics", "diagnostics"),) if summary else None,
                )
            )
            return

        shown_sentence_ids = set(self.shown_sentence_ids)
        recent_sentence_ids = set(self.recent_sentence_ids)
        due_cards = tuple(due_cards)
        generation = getattr(self, "_selection_generation", 0) + 1
        self._selection_generation = generation

        def select_task() -> Optional[ReviewTask]:
            selection_started = time.perf_counter()
            avoid_sentence_ids = shown_sentence_ids | recent_sentence_ids
            append_debug_log(
                "review_task_selection_start",
                due_card_count=len({card.card_id for card in due_cards}),
                avoided_sentence_count=len(avoid_sentence_ids),
                database_path=str(self.db_path),
            )
            task = select_review_task(
                self.db_path,
                due_cards,
                self.config.language,
                shown_sentence_ids,
                _candidate_limit_for_recent_avoidance(
                    self.config.candidate_limit,
                    len(avoid_sentence_ids),
                ),
                self.config.min_sentence_words,
                self.config.max_sentence_words,
                self.config.query_term_limit,
                self.config.matching_mode,
                soft_avoid_sentence_ids=recent_sentence_ids,
            )
            append_debug_log(
                "review_task_selection_done",
                elapsed_ms=round((time.perf_counter() - selection_started) * 1000, 1),
                sentence_id=task.sentence_id if task is not None else None,
            )
            return task

        taskman = getattr(self.mw, "taskman", None)
        if taskman is not None and callable(getattr(taskman, "run_in_background", None)):
            self._loading = True
            self.active_task = None
            self._set_html(
                render_message_html(
                    "Finding a useful sentence",
                    "You can keep using Anki while the local corpus is searched.",
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    show_refresh=False,
                )
            )
            try:
                taskman.run_in_background(
                    select_task,
                    lambda future: self._on_task_selection_done(
                        future,
                        generation,
                        retry_with_fresh_cards=cache_hit,
                    ),
                )
            except Exception as exc:
                self._show_task_selection_error(exc)
            return

        try:
            task = select_task()
        except Exception as exc:
            self._show_task_selection_error(exc)
            return
        self._show_task(task, retry_with_fresh_cards=cache_hit)

    def _on_task_selection_done(
        self,
        future: Any,
        generation: Optional[int] = None,
        retry_with_fresh_cards: bool = False,
    ) -> None:
        expected_generation = (
            getattr(self, "_selection_generation", 0) if generation is None else generation
        )
        if expected_generation != getattr(self, "_selection_generation", expected_generation):
            return
        try:
            task = future.result()
        except Exception as exc:
            self._loading = False
            self._show_task_selection_error(exc)
            return
        self._loading = False
        self._show_task(task, retry_with_fresh_cards=retry_with_fresh_cards)

    def _invalidate_pending_selection(self) -> None:
        self._selection_generation = getattr(self, "_selection_generation", 0) + 1
        self._loading = False

    def _on_dialog_finished(self, _result: Any = None) -> None:
        self._invalidate_pending_selection()
        summary = self._session_summary_text()
        if not summary or getattr(self, "_session_summary_shown", False):
            return
        self._session_summary_shown = True
        self._show_info("Session complete\n\n%s" % summary)

    def _show_task_selection_error(self, exc: Exception) -> None:
        self._loading = False
        self.active_task = None
        append_debug_log("review_task_selection_error", error=str(exc))
        self._set_html(
            render_message_html(
                "No sentence could be selected",
                str(exc),
                dark_mode=self._dark_mode(),
                font_size=self.config.font_size,
                action_label="Diagnostics",
                action="diagnostics",
            )
        )

    def _show_task(
        self,
        task: Optional[ReviewTask],
        retry_with_fresh_cards: bool = False,
    ) -> None:
        self._loading = False
        if task is None:
            if retry_with_fresh_cards:
                append_debug_log("review_task_selection_retry_with_fresh_cards")
                self._due_cards_cache = None
                self._load_next_task(refresh_due_cards=True)
                return
            self.active_task = None
            self._set_html(
                render_message_html(
                    "No matching sentence",
                    "No matching contextual sentences were found for your due words. Run Diagnostics, import more sentences, or switch to standard Anki reviews.",
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Diagnostics",
                    action="diagnostics",
                    extra_actions=(("Standard Reviews", "standard_review"),),
                )
            )
            return

        self.active_task = task
        self._mark_sentence_shown(task.sentence_id)
        self._render_task(task)

    def _on_bridge_command(self, *args: Any) -> bool:
        message = _bridge_message(args)
        if not message:
            return True

        try:
            payload = json.loads(message)
        except Exception:
            return True

        if payload.get("action") == "submit":
            unknown_keys = payload.get("unknown_keys")
            if unknown_keys is None:
                unknown_keys = payload.get("unknown_lemmas") or []
            self._submit_answer(unknown_keys, payload.get("unknown_card_ids") or [])
        elif payload.get("action") == "next":
            self._due_cards_cache = None
            self._load_next_task(refresh_due_cards=True)
        elif payload.get("action") == "standard_review":
            self._open_standard_review()
        elif payload.get("action") == "lookup":
            self._open_lookup(payload.get("words") or [])
        elif payload.get("action") == "translate_sentence":
            self._request_translation(
                payload.get("sentence") or "",
                "sentence",
                payload.get("request_id") or 0,
            )
        elif payload.get("action") == "hover_translate":
            self._request_translation(
                payload.get("text") or "",
                "hover",
                payload.get("request_id") or 0,
            )
        elif payload.get("action") == "play_media":
            self._play_media(payload.get("source") or "")
        elif payload.get("action") == "speak_sentence":
            self._request_sentence_tts()
        elif payload.get("action") == "settings":
            self._open_settings()
        elif payload.get("action") == "diagnostics":
            self._open_diagnostics()
        elif payload.get("action") == "undo":
            self._undo_last_review()
        elif payload.get("action") == "toggle_favorite":
            self._toggle_active_favorite()

        return True

    def _submit_answer(self, unknown_keys: Iterable[str], unknown_card_ids: Iterable[Any] = ()) -> None:
        if self.active_task is None:
            self._load_next_task()
            return

        try:
            summary = answer_review_task(
                self.mw,
                self.active_task,
                unknown_keys,
                self.config,
                unknown_card_ids=unknown_card_ids,
            )
        except Exception as exc:
            self._set_html(
                render_message_html(
                    "Could not grade cards",
                    str(exc),
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Diagnostics",
                    action="diagnostics",
                    extra_actions=(("Standard Reviews", "standard_review"),),
                )
            )
            return

        self.answered_card_ids.update(summary.known_card_ids)
        self.review_history.append(
            (self.active_task, list(summary.answered_card_ids), summary.undo_snapshot)
        )
        session_results = getattr(self, "_session_results", None)
        if session_results is None:
            session_results = []
            self._session_results = session_results
        session_results.append((len(summary.known_card_ids), len(summary.unknown_card_ids)))
        forgotten_words = [
            str(item.target_word or "").strip()
            for item in (self.active_task.target_words or ())
            if item.card_id in set(summary.unknown_card_ids)
            and str(item.target_word or "").strip()
        ]
        session_forgotten_words = getattr(self, "_session_forgotten_words", None)
        if session_forgotten_words is None:
            session_forgotten_words = []
            self._session_forgotten_words = session_forgotten_words
        session_forgotten_words.append(list(dict.fromkeys(forgotten_words)))
        self.active_task = None
        interrupted_tasks = getattr(self, "_interrupted_tasks", [])
        if interrupted_tasks:
            task = interrupted_tasks.pop(0)
            self.active_task = task
            self._render_task(task)
            return
        self._load_next_task()

    def _undo_last_review(self) -> None:
        if not self.review_history:
            return

        interrupted_task = self.active_task
        task, answered_card_ids, undo_snapshot = self.review_history.pop()
        try:
            if undo_snapshot is not None:
                restore_answer_snapshot(self.mw, undo_snapshot)
            else:
                _undo_last_anki_operation(self.mw)
        except Exception as exc:
            self.review_history.append((task, answered_card_ids, undo_snapshot))
            self._set_html(
                render_message_html(
                    "Could not undo last review",
                    str(exc),
                    dark_mode=self._dark_mode(),
                    font_size=self.config.font_size,
                    action_label="Diagnostics",
                    action="diagnostics",
                )
            )
            return

        self.answered_card_ids.difference_update(answered_card_ids)
        session_results = getattr(self, "_session_results", [])
        if session_results:
            session_results.pop()
        session_forgotten_words = getattr(self, "_session_forgotten_words", [])
        if session_forgotten_words:
            session_forgotten_words.pop()
        if interrupted_task is not None and interrupted_task is not task:
            interrupted_tasks = getattr(self, "_interrupted_tasks", None)
            if interrupted_tasks is None:
                interrupted_tasks = []
                self._interrupted_tasks = interrupted_tasks
            interrupted_tasks.insert(0, interrupted_task)
        self.active_task = task
        self._render_task(task)

    def _render_task(self, task: ReviewTask) -> None:
        from .favorites import is_favorite_sentence

        completed, total = self._today_progress()
        database_path = getattr(self, "db_path", None)
        try:
            favorite = bool(
                database_path
                and is_favorite_sentence(Path(database_path), task.sentence_id)
            )
        except (TypeError, ValueError):
            favorite = False
        self._set_html(
            render_task_html(
                task,
                dark_mode=self._dark_mode(),
                font_size=self.config.font_size,
                progress_completed=completed,
                progress_total=total,
                can_undo=bool(getattr(self, "review_history", [])),
                is_favorite=favorite,
            )
        )

    def _toggle_active_favorite(self) -> None:
        task = self.active_task
        if task is None:
            self._notify_favorite_changed(False, "There is no active sentence to save.")
            return
        try:
            from .favorites import toggle_favorite_sentence

            saved = toggle_favorite_sentence(self.db_path, task)
            self._notify_favorite_changed(saved, "")
        except Exception:
            self._notify_favorite_changed(False, "Could not update sentence favorites.")

    def _notify_favorite_changed(self, saved: bool, error: str) -> None:
        try:
            self.web.eval(
                "window.contextualFavoriteChanged(%s, %s);"
                % (
                    "true" if saved else "false",
                    json.dumps(str(error or ""), ensure_ascii=False),
                )
            )
        except Exception:
            pass

    def _today_progress(self) -> Tuple[int, int]:
        goal_ids = set(getattr(self, "today_goal_card_ids", set()))
        reviewed_ids = {
            card_id
            for _task, card_ids, _snapshot in getattr(self, "review_history", [])
            for card_id in card_ids
        }
        return len(reviewed_ids & goal_ids), len(goal_ids)

    def _session_summary_text(self) -> str:
        results = list(getattr(self, "_session_results", []) or [])
        if not results:
            return ""
        remembered = sum(known for known, _forgotten in results)
        forgotten = sum(forgotten for _known, forgotten in results)
        reviewed = remembered + forgotten
        summary = (
            "Reviewed %s card%s across %s sentence%s. Remembered: %s. Forgotten: %s."
            % (
                reviewed,
                "" if reviewed == 1 else "s",
                len(results),
                "" if len(results) == 1 else "s",
                remembered,
                forgotten,
            )
        )
        forgotten_words = list(
            dict.fromkeys(
                word
                for words in getattr(self, "_session_forgotten_words", []) or []
                for word in words
                if str(word or "").strip()
            )
        )
        if forgotten_words:
            summary += "\n\nForgotten words:\n" + "\n".join(
                "- %s" % word for word in forgotten_words
            )
        return summary

    def _mark_sentence_shown(self, sentence_id: int) -> None:
        self.shown_sentence_ids.add(sentence_id)
        self.recent_sentence_ids.add(sentence_id)
        self.recent_sentence_ids = _remember_recent_sentence_id(
            self.db_path,
            self.config.language,
            sentence_id,
        )

    def _set_html(self, html: str) -> None:
        try:
            try:
                self.web.stdHtml(html, context=self)
            except TypeError:
                self.web.stdHtml(html)
            except AttributeError:
                self.web.setHtml(html)
        except RuntimeError:
            # The background selection callback may finish after the dialog
            # has already been closed and its Qt webview deleted.
            return

    def _dark_mode(self) -> bool:
        return _is_dark_mode(self.mw)

    def _open_standard_review(self) -> None:
        try:
            self._dialog.close()
        except Exception:
            pass
        try:
            self.mw.moveToState("review")
        except Exception:
            pass

    def _open_settings(self) -> None:
        try:
            self._dialog.close()
        except Exception:
            pass
        try:
            from .dialogs import open_settings_dialog

            open_settings_dialog(self.mw, self.addon_name)
        except Exception as exc:
            self._show_warning("Could not open settings:\n\n%s" % exc)

    def _open_diagnostics(self) -> None:
        try:
            from .dialogs import show_diagnostics_dialog

            show_diagnostics_dialog(self.mw, self.addon_name)
        except Exception as exc:
            self._show_warning("Could not open diagnostics:\n\n%s" % exc)

    def _open_lookup(self, words: Iterable[str]) -> None:
        template = (self.config.dictionary_url_template or "").strip()
        if not template:
            return
        try:
            from aqt.utils import openLink
        except Exception:
            return

        opened = 0
        for word in words:
            cleaned = str(word or "").strip()
            if not cleaned:
                continue
            url = (
                template.replace("{word}", quote(cleaned))
                .replace("{language}", quote(self.config.language))
                .replace("{word_raw}", cleaned)
            )
            if not _is_safe_external_url(url):
                self._show_warning("Dictionary links must use an http:// or https:// URL.")
                return
            openLink(url)
            opened += 1
            if opened >= 3:
                break

    def _request_translation(self, text: str, kind: str, request_id: Any = 0) -> None:
        value = str(text or "").strip()
        translation_kind = "hover" if kind == "hover" else "sentence"
        try:
            numeric_request_id = int(request_id or 0)
        except (TypeError, ValueError):
            numeric_request_id = 0
        if not value:
            self._notify_translation_finished(
                translation_kind,
                numeric_request_id,
                value,
                "",
                "There is no text to translate.",
            )
            return

        active_task = self.active_task
        if active_task is None:
            return
        sentence_id = active_task.sentence_id
        source_language = active_task.language or self.config.language
        target_language = self.config.native_language or "en"

        def translate() -> str:
            from .translation import translate_text

            return translate_text(value, source_language, target_language)

        def done(future: Any) -> None:
            current_task = self.active_task
            if current_task is None or current_task.sentence_id != sentence_id:
                return
            try:
                translated = str(future.result() or "").strip()
                error = "" if translated else "No translation was returned."
            except Exception as exc:
                translated = ""
                error = _friendly_translation_error(exc)
            self._notify_translation_finished(
                translation_kind,
                numeric_request_id,
                value,
                translated,
                error,
            )

        taskman = getattr(self.mw, "taskman", None)
        if taskman is not None and callable(getattr(taskman, "run_in_background", None)):
            try:
                taskman.run_in_background(translate, done)
                return
            except Exception as exc:
                self._notify_translation_finished(
                    translation_kind,
                    numeric_request_id,
                    value,
                    "",
                    _friendly_translation_error(exc),
                )
                return

        try:
            translated = translate()
            error = "" if translated else "No translation was returned."
        except Exception as exc:
            translated = ""
            error = _friendly_translation_error(exc)
        self._notify_translation_finished(
            translation_kind,
            numeric_request_id,
            value,
            translated,
            error,
        )

    def _notify_translation_finished(
        self,
        kind: str,
        request_id: int,
        source_text: str,
        translated_text: str,
        error: str,
    ) -> None:
        arguments = json.dumps(
            [kind, request_id, source_text, translated_text, error],
            ensure_ascii=False,
        ).replace("</", "<\\/")
        try:
            self.web.eval("window.contextualTranslationFinished(...%s);" % arguments)
        except Exception:
            pass

    def _play_media(self, source: str) -> None:
        filename = unquote(str(source or "").strip())
        if not filename:
            return
        try:
            media_dir = Path(self.mw.col.media.dir()).resolve()
            path = (media_dir / filename).resolve()
            path.relative_to(media_dir)
            if not path.is_file():
                raise FileNotFoundError(path)
            from aqt.sound import av_player

            av_player.play_file(str(path))
        except Exception as exc:
            self._show_warning("Could not play media:\n\n%s" % exc)

    def _request_sentence_tts(self) -> None:
        task = self.active_task
        if task is None:
            self._notify_tts_finished("There is no sentence to read.")
            return

        sentence_id = task.sentence_id
        sentence = task.full_text
        language = task.language or self.config.language

        def generate() -> Path:
            from .tts import synthesize_sentence

            return synthesize_sentence(sentence, language)

        taskman = getattr(self.mw, "taskman", None)
        if taskman is not None and callable(getattr(taskman, "run_in_background", None)):
            try:
                taskman.run_in_background(
                    generate,
                    lambda future: self._on_sentence_tts_done(future, sentence_id),
                )
                return
            except Exception as exc:
                self._notify_tts_finished(_friendly_tts_error(exc))
                return

        try:
            path = generate()
            self._play_tts_path(path)
            self._notify_tts_finished("")
        except Exception as exc:
            self._notify_tts_finished(_friendly_tts_error(exc))

    def _on_sentence_tts_done(self, future: Any, sentence_id: int) -> None:
        active_task = self.active_task
        if active_task is None or active_task.sentence_id != sentence_id:
            return
        try:
            path = Path(future.result())
            self._play_tts_path(path)
            self._notify_tts_finished("")
        except Exception as exc:
            self._notify_tts_finished(_friendly_tts_error(exc))

    def _play_tts_path(self, path: Path) -> None:
        from .tts import tts_cache_dir

        cache_dir = tts_cache_dir()
        resolved = Path(path).resolve()
        resolved.relative_to(cache_dir)
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        from aqt.sound import av_player

        av_player.play_file(str(resolved))

    def _notify_tts_finished(self, error: str) -> None:
        try:
            self.web.eval(
                "window.contextualTtsFinished(%s);"
                % json.dumps(str(error or ""), ensure_ascii=False)
            )
        except Exception:
            pass

    def _show_warning(self, message: str) -> None:
        try:
            from aqt.utils import showWarning

            showWarning(message)
        except Exception:
            pass

    def _show_info(self, message: str) -> None:
        try:
            from aqt.utils import showInfo

            showInfo(message)
        except Exception:
            pass


def _bridge_message(args: Any) -> str:
    for arg in args:
        if isinstance(arg, str):
            return arg
    return ""


def _friendly_tts_error(exc: Exception) -> str:
    message = str(exc or "").strip()
    if "bundled Edge TTS" in message:
        return message
    return "Could not read the sentence. Check your internet connection and try again."


def _friendly_translation_error(exc: Exception) -> str:
    message = str(exc or "").strip()
    if "bundled deep-translator" in message:
        return message
    return "Translation unavailable. Check your internet connection."


def _is_safe_external_url(url: str) -> bool:
    try:
        parsed = urlsplit(str(url or "").strip())
    except Exception:
        return False
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _undo_last_anki_operation(mw: Any) -> None:
    for owner, method_names in (
        (mw, ("onUndo", "undo")),
        (getattr(mw, "col", None), ("undo",)),
    ):
        for method_name in method_names:
            method = getattr(owner, method_name, None)
            if callable(method):
                method()
                return
    raise RuntimeError("Anki undo is unavailable.")


def _is_dark_mode(mw: Any) -> bool:
    try:
        from aqt.theme import theme_manager

        for attr in ("night_mode", "is_night_mode"):
            value = getattr(theme_manager, attr, None)
            if callable(value):
                return bool(value())
            if value is not None:
                return bool(value)
    except Exception:
        pass

    for owner in (mw, getattr(mw, "pm", None)):
        for attr in ("night_mode", "nightMode", "dark_mode"):
            try:
                value = getattr(owner, attr, None)
                if callable(value):
                    return bool(value())
                if value is not None:
                    return bool(value)
            except Exception:
                pass
    return False


def _candidate_limit_for_recent_avoidance(base_limit: int, avoided_count: int) -> int:
    base = max(1, int(base_limit or 1))
    return base + min(max(0, int(avoided_count or 0)), RECENT_SENTENCE_LIMIT)


def _load_recent_sentence_ids(db_path: Path, language: str) -> Set[int]:
    history_path = _recent_sentence_history_path()
    histories = _read_recent_sentence_histories(history_path)
    return set(_clean_sentence_id_list(histories.get(_recent_sentence_key(db_path, language))))


def _remember_recent_sentence_id(
    db_path: Path,
    language: str,
    sentence_id: int,
    limit: int = RECENT_SENTENCE_LIMIT,
) -> Set[int]:
    try:
        cleaned_sentence_id = int(sentence_id)
    except Exception:
        return _load_recent_sentence_ids(db_path, language)
    if cleaned_sentence_id <= 0:
        return _load_recent_sentence_ids(db_path, language)

    history_path = _recent_sentence_history_path()
    histories = _read_recent_sentence_histories(history_path)
    key = _recent_sentence_key(db_path, language)
    ids = _clean_sentence_id_list(histories.get(key))
    ids = [existing for existing in ids if existing != cleaned_sentence_id]
    ids.append(cleaned_sentence_id)
    ids = ids[-max(1, int(limit or 1)) :]
    histories[key] = ids
    try:
        _write_recent_sentence_histories(history_path, histories)
    except Exception:
        pass
    return set(ids)


def _recent_sentence_history_path() -> Path:
    return addon_user_root() / RECENT_SENTENCE_HISTORY_PATH


def _recent_sentence_key(db_path: Path, language: str) -> str:
    try:
        resolved = Path(db_path).expanduser().resolve()
    except Exception:
        resolved = Path(db_path)
    return "%s|%s" % (resolved, str(language or "").strip().lower())


def _read_recent_sentence_histories(path: Path) -> Dict[str, List[int]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    histories = raw.get("histories")
    if not isinstance(histories, dict):
        return {}
    return {str(key): _clean_sentence_id_list(value) for key, value in histories.items()}


def _write_recent_sentence_histories(path: Path, histories: Dict[str, List[int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "histories": histories}
    tmp_path = path.with_name("%s.tmp" % path.name)
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def _clean_sentence_id_list(value: Any) -> List[int]:
    if not isinstance(value, list):
        return []
    ids: List[int] = []
    seen: Set[int] = set()
    for item in value:
        try:
            sentence_id = int(item)
        except Exception:
            continue
        if sentence_id <= 0 or sentence_id in seen:
            continue
        seen.add(sentence_id)
        ids.append(sentence_id)
    return ids[-RECENT_SENTENCE_LIMIT:]
