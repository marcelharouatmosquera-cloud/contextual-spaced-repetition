"""User flows where network replies arrive after retry, undo, or closing."""

from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from contextual_review.config import normalize_config
from contextual_review.reviewer import ContextualReviewDialog
from contextual_review.types import ReviewTask


class ReviewAsyncLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.dialog = d = ContextualReviewDialog.__new__(ContextualReviewDialog)
        d.config = normalize_config({"language": "de", "native_language": "en"})
        d.active_task = ReviewTask(7, "de", "Das Haus.", None, [], {})
        self.callbacks = []
        d.mw = SimpleNamespace(taskman=SimpleNamespace(
            run_in_background=lambda work, done: self.callbacks.append(done)
        ))
        self.notifications = []
        d.web = SimpleNamespace(eval=self.notifications.append)
        d._tts_sentence_ids_in_flight = set()
        d._tts_ready_paths = {}
        d._tts_play_when_ready = set()
        self.played = []
        d._play_tts_path = self.played.append
        d._session_summary_text = lambda: ""
        d._today_progress = lambda: (0, 0, 0)
        d._dark_mode = lambda: False
        d._set_html = lambda html: None

    def complete(self, index, result=None, error=None):
        future = Future()
        if error is not None:
            future.set_exception(error)
        else:
            future.set_result(result)
        self.callbacks[index](future)

    def test_retry_wins_when_original_translation_finishes_later(self):
        d = self.dialog
        d._request_translation("Das Haus.", "sentence", 1)
        d._request_translation("Das Haus.", "sentence", 2)
        self.complete(1, "The house.")
        self.complete(0, "Old translation.")
        self.assertEqual(d.active_task.translation, "The house.")
        self.assertEqual(len(self.notifications), 1)

    def test_undo_to_same_sentence_rejects_previous_page_translation(self):
        d = self.dialog
        d._render_task(d.active_task)
        d._request_translation("Das Haus.", "sentence", 1)
        # Undo re-renders the same sentence and JS restarts request IDs at 1.
        d._render_task(d.active_task)
        self.complete(0, "Old page translation.")
        self.assertIsNone(d.active_task.translation)
        self.assertEqual(self.notifications, [])

    def test_audio_does_not_start_after_review_window_is_closed(self):
        d = self.dialog
        d._request_sentence_tts()
        d._on_dialog_finished()
        self.complete(0, Path("sentence.mp3"))
        self.assertEqual(self.played, [])
        self.assertEqual(self.notifications, [])

    def test_old_audio_failure_does_not_reset_new_sentence_controls(self):
        d = self.dialog
        d._request_sentence_tts()
        d.active_task = ReviewTask(8, "de", "Die Katze.", None, [], {})
        d._request_sentence_tts()
        self.complete(0, error=RuntimeError("old audio failed"))
        self.assertEqual(self.notifications, [])
        self.complete(1, Path("cat.mp3"))
        self.assertEqual(self.played, [Path("cat.mp3")])

    def test_translation_does_not_update_closed_review(self):
        d = self.dialog
        d._request_translation("Das Haus.", "sentence", 1)
        d._on_dialog_finished()
        self.complete(0, "The house.")
        self.assertEqual(self.notifications, [])

    def test_waiting_learning_steps_are_not_announced_as_finished(self):
        d = self.dialog
        d.db_path = Path(__file__)
        d.answered_card_ids = set()
        d.learning_card_ids = {42}
        d._load_queued_mined_task = lambda **kwargs: False
        messages = []
        d._show_message = lambda *args, **kwargs: messages.append(args)
        with patch("contextual_review.reviewer.collect_due_cards", return_value=[]):
            d._load_next_task(refresh_due_cards=True)
        self.assertEqual(messages[0][0], "Nothing due right now")
        self.assertIn("Learning or relearning cards can return", messages[0][1])
        self.assertEqual(d.learning_card_ids, {42})


if __name__ == "__main__":
    unittest.main()
