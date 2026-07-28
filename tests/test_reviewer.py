from __future__ import annotations

import json
import os
import tempfile
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

from contextual_review import reviewer
from contextual_review.config import USER_ROOT_ENV
from contextual_review.config import normalize_config
from contextual_review.reviewer import ContextualReviewDialog, _is_safe_external_url
from contextual_review.types import DueCard, ReviewTask, TargetWordDefinition, Token


class ReviewerBridgeTests(unittest.TestCase):
    def _recall_task(self) -> ReviewTask:
        return ReviewTask(
            sentence_id=7,
            language="de",
            full_text="Er ging.",
            translation="He went.",
            tokens=[
                Token(
                    text="ging",
                    lemma="gehen",
                    is_word=True,
                    is_target=True,
                    card_ids=(70,),
                    direction="recall",
                    hint="to go",
                )
            ],
            card_ids_by_key={"gehen": [70]},
        )

    def test_rendering_task_auto_reads_sentence_when_enabled(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"autoplay_sentence_tts": True})
        dialog.db_path = None
        dialog.review_history = []
        dialog.today_goal_card_ids = set()
        dialog.answered_card_ids = set()
        dialog.learning_card_ids = set()
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda _html: None
        spoken = []
        dialog._request_sentence_tts = lambda: spoken.append(True)

        dialog._render_task(ReviewTask(1, "de", "Das Haus.", None, [], {}))

        self.assertEqual(spoken, [True])

    def test_web_load_finished_starts_bridge_ready_page_work(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)

        dialog._on_web_load_finished(False)
        dialog._on_web_load_finished(True)

        self.assertEqual(len(scripts), 1)
        self.assertIn("window.contextualPageReady", scripts[0])

    def test_rendering_recall_task_prepares_audio_without_playing(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"autoplay_sentence_tts": True})
        dialog.db_path = None
        dialog.review_history = []
        dialog.today_goal_card_ids = set()
        dialog.answered_card_ids = set()
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda _html: None
        spoken = []
        prepared = []
        dialog._request_sentence_tts = lambda: spoken.append(True)
        dialog._prepare_sentence_tts = lambda task: prepared.append(task.sentence_id)

        dialog._render_task(self._recall_task())

        self.assertEqual(spoken, [])
        self.assertEqual(prepared, [7])
        self.assertIsNone(dialog._revealed_sentence_id)

    def test_revealing_recall_task_autoplays_once_and_rejects_stale_sentence(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"autoplay_sentence_tts": True})
        dialog.active_task = self._recall_task()
        dialog._revealed_sentence_id = None
        spoken = []
        dialog._request_sentence_tts = lambda: spoken.append(True)

        dialog._on_bridge_command('{"action": "solution_revealed", "sentence_id": 999}')
        dialog._on_bridge_command('{"action": "solution_revealed", "sentence_id": 7}')
        dialog._on_bridge_command('{"action": "solution_revealed", "sentence_id": 7}')

        self.assertEqual(spoken, [True])
        self.assertEqual(dialog._revealed_sentence_id, 7)

    def test_manual_recall_tts_is_blocked_before_reveal(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({})
        dialog.active_task = self._recall_task()
        dialog._revealed_sentence_id = None
        errors = []
        dialog._notify_tts_finished = errors.append

        dialog._request_sentence_tts()

        self.assertEqual(errors, ["Show the solution before playing this recall sentence."])

    def test_autoplay_and_manual_tts_requests_for_one_sentence_are_coalesced(self) -> None:
        class HoldingTaskman:
            def __init__(self) -> None:
                self.calls = []

            def run_in_background(self, work, done) -> None:
                self.calls.append((work, done))

        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({})
        dialog.active_task = self._recall_task()
        dialog._revealed_sentence_id = 7
        dialog._tts_sentence_ids_in_flight = set()
        taskman = HoldingTaskman()
        dialog.mw = SimpleNamespace(taskman=taskman)

        dialog._request_sentence_tts()
        dialog._request_sentence_tts()

        self.assertEqual(len(taskman.calls), 1)
        self.assertEqual(dialog._tts_sentence_ids_in_flight, {7})

        dialog.active_task = None
        dialog._on_sentence_tts_done(Future(), 7)
        self.assertEqual(dialog._tts_sentence_ids_in_flight, set())

    def test_prepared_recall_audio_plays_immediately_after_reveal(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({})
        dialog.active_task = self._recall_task()
        dialog._revealed_sentence_id = 7
        prepared_path = Path("prepared.mp3")
        dialog._tts_ready_paths = {7: prepared_path}
        played = []
        finished = []
        dialog._play_tts_path = played.append
        dialog._notify_tts_finished = finished.append

        dialog._request_sentence_tts()

        self.assertEqual(played, [prepared_path])
        self.assertEqual(finished, [""])

    def test_review_window_opens_large_but_fits_available_screen(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        resized_to = []
        geometry = SimpleNamespace(width=lambda: 1000, height=lambda: 700)
        screen = SimpleNamespace(availableGeometry=lambda: geometry)
        dialog._dialog = SimpleNamespace(
            screen=lambda: screen,
            resize=lambda width, height: resized_to.append((width, height)),
        )

        dialog._resize_for_available_screen()

        self.assertEqual(resized_to, [(920, 616)])

    def test_start_loads_only_once(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._started = False
        loads = []
        dialog._load_next_task = lambda: loads.append("load")

        dialog.start()
        dialog.start()

        self.assertEqual(loads, ["load"])

    def test_external_links_only_allow_http_urls_with_a_host(self) -> None:
        self.assertTrue(_is_safe_external_url("https://example.com/dictionary?q=word"))
        self.assertFalse(_is_safe_external_url("javascript:alert(1)"))
        self.assertFalse(_is_safe_external_url("file:///tmp/dictionary.html"))
        self.assertFalse(_is_safe_external_url("https:///missing-host"))

    def test_bridge_routes_recovery_actions(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        calls = []
        dialog._open_diagnostics = lambda: calls.append("diagnostics")
        dialog._open_settings = lambda: calls.append("settings")
        dialog._open_standard_review = lambda: calls.append("standard_review")
        dialog._open_lookup = lambda words: calls.append(("lookup", tuple(words)))
        dialog._request_translation = lambda text, kind, request_id=0: calls.append(
            (kind, text, request_id)
        )
        dialog._mine_word = lambda word, meaning, sentence="": calls.append(
            ("mine", word, meaning, sentence)
        )
        dialog._play_media = lambda source: calls.append(("play_media", source))
        dialog._request_sentence_tts = lambda: calls.append("speak_sentence")
        dialog._undo_last_review = lambda: calls.append("undo")
        dialog._toggle_active_favorite = lambda: calls.append("toggle_favorite")

        dialog._on_bridge_command('{"action": "diagnostics"}')
        dialog._on_bridge_command('{"action": "settings"}')
        dialog._on_bridge_command('{"action": "standard_review"}')
        dialog._on_bridge_command('{"action": "lookup", "words": ["review"]}')
        dialog._on_bridge_command('{"action": "translate_sentence", "sentence": "We review."}')
        dialog._on_bridge_command('{"action": "hover_translate", "text": "We", "request_id": 7}')
        dialog._on_bridge_command(
            '{"action": "mine_word", "word": "lernen", "translation": "learn", '
            '"sentence_translation": "We learn."}'
        )
        dialog._on_bridge_command('{"action": "play_media", "source": "voice.mp3"}')
        dialog._on_bridge_command('{"action": "speak_sentence"}')
        dialog._on_bridge_command('{"action": "undo"}')
        dialog._on_bridge_command('{"action": "toggle_favorite"}')

        self.assertEqual(
            calls,
            [
                "diagnostics",
                "settings",
                "standard_review",
                ("lookup", ("review",)),
                ("sentence", "We review.", 0),
                ("hover", "We", 7),
                ("mine", "lernen", "learn", "We learn."),
                ("play_media", "voice.mp3"),
                "speak_sentence",
                "undo",
                "toggle_favorite",
            ],
        )

    def test_refresh_action_invalidates_due_card_cache(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._due_cards_cache = (DueCard(card_id=1, target_word="review", lemma="review"),)
        loads = []
        dialog._load_next_task = lambda refresh_due_cards=False: loads.append(refresh_due_cards)

        dialog._on_bridge_command('{"action": "next"}')

        self.assertIsNone(dialog._due_cards_cache)
        self.assertEqual(loads, [True])

    def test_mined_note_queues_only_one_exact_card_when_new_study_is_disabled(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config(
            {
                "include_new_cards": False,
                "included_card_templates": ["Card 1"],
                "recall_templates": ["Card 2"],
            }
        )
        dialog.mw = object()
        dialog._queued_mined_due_card_batches = []
        candidates = [
            DueCard(
                card_id=20,
                target_word="lernen",
                lemma="lernen",
                direction="recognition",
            ),
            DueCard(
                card_id=21,
                target_word="lernen",
                lemma="lernen",
                direction="recall",
            ),
        ]
        captured = []
        original = reviewer.collect_due_cards
        reviewer.collect_due_cards = lambda mw, config: captured.append(config) or candidates
        try:
            queued = dialog._queue_mined_note_for_review(
                SimpleNamespace(note_id=99, card_ids=(20, 21))
            )
        finally:
            reviewer.collect_due_cards = original

        self.assertEqual(queued, (20,))
        self.assertEqual(
            [card.card_id for card in dialog._queued_mined_due_card_batches[0]],
            [20],
        )
        self.assertEqual(captured[0].custom_search_query, "nid:99")
        self.assertTrue(captured[0].include_new_cards)
        self.assertFalse(captured[0].include_due_cards)

    def test_mined_note_uses_normal_new_queue_when_new_study_is_enabled(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"include_new_cards": True})
        dialog._queued_mined_due_card_batches = []

        queued = dialog._queue_mined_note_for_review(
            SimpleNamespace(note_id=99, card_ids=(20, 21))
        )

        self.assertEqual(queued, ())
        self.assertEqual(dialog._queued_mined_due_card_batches, [])

    def test_queued_mined_card_becomes_the_only_next_selection_batch(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        mined = DueCard(card_id=20, target_word="lernen", lemma="lernen")
        dialog._queued_mined_due_card_batches = [(mined,)]
        loads = []
        dialog._load_next_task = lambda: loads.append(True)

        loaded = dialog._load_queued_mined_task()

        self.assertTrue(loaded)
        self.assertEqual(dialog._due_cards_cache, (mined,))
        self.assertTrue(dialog._due_cards_cache_is_mined)
        self.assertEqual(loads, [True])

    def test_mined_follow_up_can_reuse_the_sentence_it_was_mined_from(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.db_path = SimpleNamespace(exists=lambda: True)
        dialog.config = normalize_config({})
        dialog.shown_sentence_ids = {7}
        dialog.recent_sentence_ids = {7}
        dialog.answered_card_ids = set()
        dialog.review_history = []
        dialog.active_task = None
        dialog._loading = False
        dialog._due_cards_cache = (
            DueCard(card_id=20, target_word="lernen", lemma="lernen"),
        )
        dialog._due_cards_cache_is_mined = True
        dialog._selection_generation = 0
        dialog._today_goal_initialized = True
        dialog.today_goal_card_ids = set()
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda _html: None
        dialog._mark_sentence_shown = lambda _sentence_id: None
        rendered = []
        dialog._render_task = rendered.append
        dialog.mw = object()
        task = ReviewTask(7, "en", "We learn.", None, [], {"lernen": [20]})
        calls = []
        original = reviewer.select_review_task
        reviewer.select_review_task = lambda *args, **kwargs: (
            calls.append((args[3], kwargs.get("soft_avoid_sentence_ids"))) or task
        )
        try:
            dialog._load_next_task()
        finally:
            reviewer.select_review_task = original

        self.assertEqual(calls, [(set(), {7})])
        self.assertEqual(rendered, [task])

    def test_undo_removes_the_mined_card_from_the_follow_up_queue(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        kept = DueCard(card_id=10, target_word="keep", lemma="keep")
        removed = DueCard(card_id=20, target_word="remove", lemma="remove")
        dialog._queued_mined_due_card_batches = [(kept,), (removed,)]

        dialog._remove_queued_mined_cards((20,))

        self.assertEqual(dialog._queued_mined_due_card_batches, [(kept,)])

    def test_grade_failure_screen_has_recovery_actions(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.active_task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [1]},
        )
        dialog.mw = object()
        dialog.config = normalize_config({})
        html = []
        dialog._set_html = html.append
        dialog._dark_mode = lambda: False

        original = reviewer.answer_review_task
        try:
            reviewer.answer_review_task = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom"))

            dialog._submit_answer(["review"])
        finally:
            reviewer.answer_review_task = original

        self.assertEqual(len(html), 1)
        self.assertIn("Could not grade cards", html[0])
        self.assertIn("diagnostics", html[0])
        self.assertIn("standard_review", html[0])

    def test_hover_translation_runs_in_background_and_returns_to_webview(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.active_task = ReviewTask(
            4, "de", "Das Haus.", None, [], {"haus": [1]}
        )
        dialog.config = normalize_config({"language": "de", "native_language": "en"})

        class ImmediateTaskman:
            def run_in_background(self, work, done) -> None:
                future = Future()
                try:
                    future.set_result(work())
                except Exception as exc:
                    future.set_exception(exc)
                done(future)

        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)
        dialog.mw = SimpleNamespace(taskman=ImmediateTaskman())

        from contextual_review import translation

        original = translation.translate_text
        calls = []
        try:
            translation.translate_text = lambda text, source, target: (
                calls.append((text, source, target)) or "the"
            )
            dialog._request_translation("Das", "hover", 12)
        finally:
            translation.translate_text = original

        self.assertEqual(calls, [("Das", "de", "en")])
        self.assertEqual(len(scripts), 1)
        self.assertIn('["hover", 12, "Das", "the", ""]', scripts[0])

    def test_automatic_sentence_translation_updates_the_active_task(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"language": "de", "native_language": "en"})
        dialog.active_task = ReviewTask(9, "de", "Das Haus.", None, [], {})
        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)
        dialog.mw = SimpleNamespace(taskman=None)

        from contextual_review import translation

        original = translation.translate_text
        try:
            translation.translate_text = lambda text, source, target: "The house."
            dialog._request_translation("Das Haus.", "sentence", 0)
        finally:
            translation.translate_text = original

        self.assertEqual(dialog.active_task.translation, "The house.")
        self.assertIn('["sentence", 0, "Das Haus.", "The house.", ""]', scripts[0])

    def test_automatic_sentence_translation_reports_background_timeout(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.config = normalize_config({"language": "ru", "native_language": "en"})
        dialog.active_task = ReviewTask(9, "ru", "Какими навыками?", None, [], {})
        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)

        class ImmediateTaskman:
            def run_in_background(self, work, done) -> None:
                future = Future()
                try:
                    future.set_result(work())
                except Exception as exc:
                    future.set_exception(exc)
                done(future)

        dialog.mw = SimpleNamespace(taskman=ImmediateTaskman())
        from contextual_review import translation

        original = translation.translate_text
        try:
            translation.translate_text = lambda *args: (_ for _ in ()).throw(
                TimeoutError("request timed out")
            )
            dialog._request_translation("Какими навыками?", "sentence", 4)
        finally:
            translation.translate_text = original

        self.assertIn("Automatic translation timed out", scripts[0])

    def test_submit_only_suppresses_known_cards_in_current_window(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.active_task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
            target_words=(
                TargetWordDefinition(10, "review", "revise"),
                TargetWordDefinition(20, "card", "flashcard"),
            ),
        )
        dialog.mw = object()
        dialog.config = normalize_config({})
        dialog.answered_card_ids = set()
        dialog.today_goal_card_ids = {10, 20}
        dialog.review_history = []
        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)
        loads = []
        dialog._load_next_task = lambda refresh_due_cards=False: loads.append(refresh_due_cards)

        original = reviewer.answer_review_task
        try:
            reviewer.answer_review_task = lambda *args, **kwargs: SimpleNamespace(
                answered_card_ids=[10, 20],
                unknown_card_ids=[10],
                known_card_ids=[20],
                completed_card_ids=[20],
                learning_card_ids=[10],
            )

            dialog._submit_answer(["review"])
        finally:
            reviewer.answer_review_task = original

        self.assertEqual(dialog.answered_card_ids, {20})
        self.assertEqual(dialog.learning_card_ids, {10})
        self.assertEqual(dialog.review_history[0][1], [10, 20])
        self.assertEqual(dialog._session_forgotten_words, [["review"]])
        self.assertIn("window.contextualProgressChanged(1, 1, 2);", scripts)
        self.assertIn("window.contextualSetUndoAvailable(true);", scripts)
        self.assertIsNone(dialog._due_cards_cache)
        self.assertEqual(loads, [True])

    def test_submit_does_not_complete_good_card_with_an_intraday_step(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.active_task = ReviewTask(1, "en", "We review.", None, [], {"review": [10]})
        dialog.mw = object()
        dialog.config = normalize_config({})
        dialog.answered_card_ids = set()
        dialog.learning_card_ids = set()
        dialog.review_history = []
        dialog._load_next_task = lambda refresh_due_cards=False: None

        original = reviewer.answer_review_task
        try:
            reviewer.answer_review_task = lambda *args, **kwargs: SimpleNamespace(
                answered_card_ids=[10],
                unknown_card_ids=[],
                known_card_ids=[10],
                completed_card_ids=[],
                learning_card_ids=[10],
            )
            dialog._submit_answer([])
        finally:
            reviewer.answer_review_task = original

        self.assertEqual(dialog.answered_card_ids, set())
        self.assertEqual(dialog.learning_card_ids, {10})
        self.assertEqual(dialog.review_history[0][1], [10])

    def test_undo_restores_previous_contextual_sentence(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[Token(text="review", lemma="review", is_word=True, is_target=True, card_ids=(10,))],
            card_ids_by_key={"review": [10]},
        )
        dialog.config = normalize_config({})
        dialog.review_history = [(task, [10], None)]
        dialog.answered_card_ids = {10, 20}
        dialog.active_task = None
        dialog._selection_generation = 4
        dialog._loading = True
        dialog._dark_mode = lambda: False
        html = []
        dialog._set_html = html.append

        class FakeMw:
            def __init__(self) -> None:
                self.undo_called = False

            def onUndo(self) -> None:
                self.undo_called = True

        mw = FakeMw()
        dialog.mw = mw

        dialog._undo_last_review()

        self.assertTrue(mw.undo_called)
        self.assertEqual(dialog.active_task, task)
        self.assertEqual(dialog.answered_card_ids, {20})
        self.assertEqual(dialog._selection_generation, 5)
        self.assertFalse(dialog._loading)
        self.assertIn("review", html[-1])

    def test_undo_restores_a_cards_previous_learning_progress_state(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [10]})
        dialog.review_history = [(task, [10], None, set(), {10})]
        dialog.answered_card_ids = {10}
        dialog.learning_card_ids = set()
        dialog.today_goal_card_ids = {10}
        dialog.active_task = None
        dialog._selection_generation = 0
        dialog._loading = False
        dialog._session_results = []
        dialog._session_forgotten_words = []
        dialog.web = SimpleNamespace(eval=lambda _script: None)
        dialog._render_task = lambda restored: setattr(dialog, "active_task", restored)
        dialog.mw = SimpleNamespace(onUndo=lambda: None)

        dialog._undo_last_review()

        self.assertEqual(dialog.answered_card_ids, set())
        self.assertEqual(dialog.learning_card_ids, {10})
        self.assertEqual(dialog._today_progress(), (0, 1, 1))

    def test_ctrl_z_undoes_the_latest_mined_note_before_review_history(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        marker = reviewer.AnkiUndoMarker(last_step=55, label="Add Contextual Note")
        dialog._mining_undo_markers = [marker]
        dialog.review_history = []
        scripts = []
        dialog.web = SimpleNamespace(eval=scripts.append)

        class FakeCollection:
            def __init__(self) -> None:
                self.undo_called = False

            def undo_status(self):
                return SimpleNamespace(last_step=55, undo="Add Contextual Note")

            def undo(self):
                self.undo_called = True

        collection = FakeCollection()
        dialog.mw = SimpleNamespace(col=collection, reset=lambda: None)

        dialog._undo_last_review()

        self.assertTrue(collection.undo_called)
        self.assertEqual(dialog._mining_undo_markers, [])
        self.assertIn("window.contextualMineUndone", scripts[0])

    def test_undo_refuses_to_revert_a_newer_unrelated_anki_action(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [10]})
        marker = reviewer.AnkiUndoMarker(last_step=42, label="Contextual Review")
        dialog.review_history = [(task, [10], marker)]
        dialog.answered_card_ids = {10}
        dialog.active_task = None
        dialog.config = normalize_config({})
        dialog._dark_mode = lambda: False
        rendered = []
        dialog._set_html = rendered.append

        class FakeCollection:
            def __init__(self) -> None:
                self.undo_called = False

            def undo_status(self):
                return SimpleNamespace(last_step=43, undo="Edit Note")

            def undo(self) -> None:
                self.undo_called = True

        dialog.mw = SimpleNamespace(col=FakeCollection())

        dialog._undo_last_review()

        self.assertFalse(dialog.mw.col.undo_called)
        self.assertEqual(dialog.review_history, [(task, [10], marker)])
        self.assertIn("another Anki action happened afterward", rendered[-1])

    def test_regrading_previous_sentence_resumes_interrupted_sentence(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        previous_task = ReviewTask(
            1, "en", "We review.", None, [], {"review": [10]}
        )
        interrupted_task = ReviewTask(
            2, "en", "Keep this sentence.", None, [], {"keep": [20]}
        )
        dialog.config = normalize_config({})
        dialog.review_history = [(previous_task, [10], None)]
        dialog.answered_card_ids = {10}
        dialog.active_task = interrupted_task
        rendered = []
        loads = []
        dialog._render_task = rendered.append
        dialog._load_next_task = lambda: loads.append("selected a new sentence")

        class FakeMw:
            def onUndo(self) -> None:
                pass

        dialog.mw = FakeMw()
        dialog._undo_last_review()

        original = reviewer.answer_review_task
        try:
            reviewer.answer_review_task = lambda *args, **kwargs: SimpleNamespace(
                answered_card_ids=[10],
                unknown_card_ids=[],
                known_card_ids=[10],
            )
            dialog._submit_answer([])
        finally:
            reviewer.answer_review_task = original

        self.assertEqual(rendered, [previous_task, interrupted_task])
        self.assertIs(dialog.active_task, interrupted_task)
        self.assertEqual(loads, [])
        self.assertEqual(dialog._interrupted_tasks, [])

    def test_empty_cached_batch_retries_before_showing_no_match(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._loading = False
        dialog._due_cards_cache = (DueCard(card_id=1, target_word="review", lemma="review"),)
        dialog.active_task = None
        retries = []
        dialog._load_next_task = lambda refresh_due_cards=False: retries.append(refresh_due_cards)

        dialog._show_task(None, retry_with_fresh_cards=True)

        self.assertIsNone(dialog._due_cards_cache)
        self.assertEqual(retries, [True])

    def test_today_progress_counts_only_initially_due_cards(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [10]})
        dialog.today_goal_card_ids = {10, 20, 30}
        dialog.answered_card_ids = {10, 20, 99}
        dialog.learning_card_ids = {30, 99}
        dialog.review_history = [
            (task, [10, 99], None),
            (task, [20], None),
        ]

        self.assertEqual(dialog._today_progress(), (2, 1, 3))

    def test_session_summary_counts_sentences_and_answer_results(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._session_results = [(2, 1), (1, 0)]
        dialog._session_forgotten_words = [["дом"], []]

        self.assertEqual(
            dialog._session_summary_text(),
            "Reviewed 4 cards across 2 sentences. Remembered: 3. Forgotten: 1."
            "\n\nForgotten words:\n- дом",
        )

    def test_closing_review_shows_session_summary_only_once(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._session_results = [(2, 1)]
        dialog._session_summary_shown = False
        dialog._invalidate_pending_selection = lambda: None
        shown = []
        dialog._show_info = shown.append

        dialog._on_dialog_finished()
        dialog._on_dialog_finished()

        self.assertEqual(
            shown,
            [
                "Session complete\n\nReviewed 3 cards across 1 sentence. "
                "Remembered: 2. Forgotten: 1."
            ],
        )

    def test_recent_sentence_history_persists_and_moves_seen_sentence_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                db_path = Path(tempdir) / "sentences.db"

                reviewer._remember_recent_sentence_id(db_path, "en", 1, limit=3)
                reviewer._remember_recent_sentence_id(db_path, "en", 2, limit=3)
                reviewer._remember_recent_sentence_id(db_path, "en", 3, limit=3)
                recent = reviewer._remember_recent_sentence_id(db_path, "en", 1, limit=3)
            finally:
                if old_root is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = old_root

            self.assertEqual(recent, {1, 2, 3})
            history_path = Path(tempdir) / "user_files" / "recent_sentence_history.json"
            payload = json.loads(history_path.read_text(encoding="utf-8"))
            key = reviewer._recent_sentence_key(db_path, "en")
            self.assertEqual(payload["histories"][key], [2, 3, 1])

    def test_load_next_task_uses_recent_history_as_soft_avoidance(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                db_path = Path(tempdir) / "sentences.db"
                db_path.write_bytes(b"sqlite placeholder")
                dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
                dialog.db_path = db_path
                dialog.config = normalize_config({"candidate_limit": 5})
                dialog.shown_sentence_ids = {10}
                dialog.recent_sentence_ids = {1, 2}
                dialog.answered_card_ids = set()
                dialog.mw = object()
                dialog._dark_mode = lambda: False
                html = []
                dialog._set_html = html.append

                calls = []
                task = ReviewTask(
                    sentence_id=3,
                    language="en",
                    full_text="We review.",
                    translation=None,
                    tokens=[],
                    card_ids_by_key={"review": [7]},
                )

                original_collect = reviewer.collect_due_cards
                original_select = reviewer.select_review_task
                try:
                    reviewer.collect_due_cards = lambda *args, **kwargs: [
                        DueCard(card_id=7, target_word="review", lemma="review")
                    ]

                    def fake_select(*args, **kwargs):
                        calls.append(
                            (
                                set(args[3]),
                                args[4],
                                set(kwargs.get("soft_avoid_sentence_ids") or ()),
                            )
                        )
                        return task

                    reviewer.select_review_task = fake_select

                    dialog._load_next_task()
                finally:
                    reviewer.collect_due_cards = original_collect
                    reviewer.select_review_task = original_select
            finally:
                if old_root is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = old_root

        self.assertEqual(calls, [({10}, 8, {1, 2})])
        self.assertEqual(dialog.active_task, task)
        self.assertIn(3, dialog.shown_sentence_ids)
        self.assertIn(3, dialog.recent_sentence_ids)
        self.assertEqual(len(html), 1)

    def test_load_next_task_uses_background_task_manager(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                db_path = Path(tempdir) / "sentences.db"
                db_path.write_bytes(b"sqlite placeholder")
                dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
                dialog.db_path = db_path
                dialog.config = normalize_config({"candidate_limit": 5})
                dialog.shown_sentence_ids = set()
                dialog.recent_sentence_ids = set()
                dialog.answered_card_ids = set()
                dialog.review_history = []
                dialog.active_task = None
                dialog._loading = False
                dialog._dark_mode = lambda: False
                html = []
                dialog._set_html = html.append

                task = ReviewTask(
                    sentence_id=3,
                    language="en",
                    full_text="We review.",
                    translation=None,
                    tokens=[],
                    card_ids_by_key={"review": [7]},
                )

                class ImmediateTaskman:
                    def __init__(self) -> None:
                        self.calls = 0

                    def run_in_background(self, work, done) -> None:
                        self.calls += 1
                        future = Future()
                        try:
                            future.set_result(work())
                        except Exception as exc:
                            future.set_exception(exc)
                        done(future)

                taskman = ImmediateTaskman()
                dialog.mw = SimpleNamespace(taskman=taskman)

                original_collect = reviewer.collect_due_cards
                original_select = reviewer.select_review_task
                try:
                    reviewer.collect_due_cards = lambda *args, **kwargs: [
                        DueCard(card_id=7, target_word="review", lemma="review")
                    ]
                    reviewer.select_review_task = lambda *args, **kwargs: task

                    dialog._load_next_task()
                finally:
                    reviewer.collect_due_cards = original_collect
                    reviewer.select_review_task = original_select
            finally:
                if old_root is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = old_root

        self.assertEqual(taskman.calls, 1)
        self.assertEqual(dialog.active_task, task)
        self.assertFalse(dialog._loading)
        self.assertIn("Finding a useful sentence", html[0])
        self.assertIn("We review.", html[-1])

    def test_due_cards_are_cached_between_tasks(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.db_path = SimpleNamespace(exists=lambda: True)
        dialog.config = normalize_config({})
        dialog.shown_sentence_ids = set()
        dialog.recent_sentence_ids = set()
        dialog.answered_card_ids = set()
        dialog.active_task = None
        dialog._loading = False
        dialog._due_cards_cache = None
        dialog._selection_generation = 0
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda html: None
        dialog._mark_sentence_shown = lambda sentence_id: None
        dialog.mw = object()
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [7]})
        collect_calls = []

        original_collect = reviewer.collect_due_cards
        original_select = reviewer.select_review_task
        try:
            reviewer.collect_due_cards = lambda *args, **kwargs: (
                collect_calls.append(True)
                or [DueCard(card_id=7, target_word="review", lemma="review")]
            )
            reviewer.select_review_task = lambda *args, **kwargs: task

            dialog._load_next_task()
            dialog.active_task = None
            dialog._load_next_task()
        finally:
            reviewer.collect_due_cards = original_collect
            reviewer.select_review_task = original_select

        self.assertEqual(len(collect_calls), 1)

    def test_cjk_database_migration_runs_once_before_first_selection(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.db_path = SimpleNamespace(exists=lambda: True)
        dialog.config = normalize_config({"language": "ko"})
        dialog.shown_sentence_ids = set()
        dialog.recent_sentence_ids = set()
        dialog.answered_card_ids = set()
        dialog.active_task = None
        dialog._loading = False
        dialog._due_cards_cache = None
        dialog._selection_generation = 0
        dialog._database_migration_pending = True
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda html: None
        dialog._mark_sentence_shown = lambda sentence_id: None
        dialog.mw = object()
        task = ReviewTask(1, "ko", "문맥을 복습한다.", None, [], {"복습한다": [7]})
        migration_calls = []

        original_collect = reviewer.collect_due_cards
        original_select = reviewer.select_review_task
        original_migrate = reviewer.migrate_database
        try:
            reviewer.collect_due_cards = lambda *args, **kwargs: [
                DueCard(card_id=7, target_word="복습한다", lemma="복습한다")
            ]
            reviewer.select_review_task = lambda *args, **kwargs: task
            reviewer.migrate_database = lambda path: migration_calls.append(path)

            dialog._load_next_task()
            dialog.active_task = None
            dialog._load_next_task()
        finally:
            reviewer.collect_due_cards = original_collect
            reviewer.select_review_task = original_select
            reviewer.migrate_database = original_migrate

        self.assertEqual(migration_calls, [dialog.db_path])

    def test_fresh_due_search_keeps_the_session_start_goal_fixed(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.db_path = SimpleNamespace(exists=lambda: True)
        dialog.config = normalize_config({})
        dialog.shown_sentence_ids = set()
        dialog.recent_sentence_ids = set()
        dialog.answered_card_ids = set()
        dialog.active_task = None
        dialog._loading = False
        dialog._due_cards_cache = None
        dialog._selection_generation = 0
        dialog._today_goal_initialized = False
        dialog.today_goal_card_ids = set()
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda html: None
        dialog._mark_sentence_shown = lambda sentence_id: None
        dialog.mw = object()

        class DueBatch(list):
            def __init__(self, card_ids):
                super().__init__(
                    DueCard(card_id=card_id, target_word=str(card_id), lemma=str(card_id))
                    for card_id in card_ids
                )
                self.today_card_ids = frozenset(card_ids)

        batches = [DueBatch([7, 8]), DueBatch([8, 9])]
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [7]})
        original_collect = reviewer.collect_due_cards
        original_select = reviewer.select_review_task
        try:
            reviewer.collect_due_cards = lambda *args, **kwargs: batches.pop(0)
            reviewer.select_review_task = lambda *args, **kwargs: task
            dialog._load_next_task()
            dialog.active_task = None
            dialog._due_cards_cache = None
            dialog._load_next_task(refresh_due_cards=True)
        finally:
            reviewer.collect_due_cards = original_collect
            reviewer.select_review_task = original_select

        self.assertEqual(dialog.today_goal_card_ids, {7, 8})

    def test_cached_again_card_waits_for_fresh_anki_due_search(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog.db_path = SimpleNamespace(exists=lambda: True)
        dialog.config = normalize_config({})
        dialog.shown_sentence_ids = set()
        dialog.recent_sentence_ids = set()
        dialog.answered_card_ids = set()
        reviewed_task = ReviewTask(1, "en", "Review this.", None, [], {"review": [7]})
        dialog.review_history = [(reviewed_task, [7], None)]
        dialog.active_task = None
        dialog._loading = False
        dialog._due_cards_cache = (
            DueCard(card_id=7, target_word="review", lemma="review"),
            DueCard(card_id=8, target_word="learn", lemma="learn"),
        )
        dialog._selection_generation = 0
        dialog._today_goal_initialized = True
        dialog.today_goal_card_ids = {7, 8}
        dialog._dark_mode = lambda: False
        dialog._set_html = lambda html: None
        dialog._mark_sentence_shown = lambda sentence_id: None
        dialog.mw = object()
        selected_card_ids = []
        task = ReviewTask(2, "en", "Learn this.", None, [], {"learn": [8]})

        original_select = reviewer.select_review_task
        try:
            def fake_select(_db, due_cards, *args, **kwargs):
                selected_card_ids.extend(card.card_id for card in due_cards)
                return task

            reviewer.select_review_task = fake_select
            dialog._load_next_task()
        finally:
            reviewer.select_review_task = original_select

        self.assertEqual(selected_card_ids, [8])

    def test_stale_background_result_is_ignored(self) -> None:
        dialog = ContextualReviewDialog.__new__(ContextualReviewDialog)
        dialog._selection_generation = 2
        dialog._loading = True
        shown = []
        dialog._show_task = shown.append
        task = ReviewTask(1, "en", "We review.", None, [], {"review": [7]})
        future = Future()
        future.set_result(task)

        dialog._on_task_selection_done(future, generation=1)

        self.assertEqual(shown, [])
        self.assertTrue(dialog._loading)


if __name__ == "__main__":
    unittest.main()
