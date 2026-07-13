from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from contextual_review.config import USER_ROOT_ENV
from contextual_review.favorites import (
    favorite_sentences,
    is_favorite_sentence,
    remove_favorite_sentence,
    toggle_favorite_sentence,
)
from contextual_review.types import ReviewTask, TargetWordDefinition


class FavoriteTests(unittest.TestCase):
    def test_favorite_persists_snapshot_and_toggles(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            previous = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                db_path = Path(tempdir) / "sentences.db"
                task = ReviewTask(
                    7,
                    "de",
                    "Das ist gut.",
                    "That is good.",
                    [],
                    {"gut": [1]},
                    target_words=(
                        TargetWordDefinition(1, "gut", "good"),
                    ),
                )

                self.assertTrue(toggle_favorite_sentence(db_path, task))
                self.assertTrue(is_favorite_sentence(db_path, 7))
                saved = favorite_sentences()
                self.assertEqual(saved[0]["text"], "Das ist gut.")
                self.assertEqual(saved[0]["translation"], "That is good.")
                self.assertEqual(saved[0]["target_words"], [{"word": "gut", "definition": "good"}])
                self.assertTrue(remove_favorite_sentence(saved[0]["key"]))
                self.assertFalse(is_favorite_sentence(db_path, 7))
            finally:
                if previous is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = previous

    def test_favorites_can_be_filtered_to_current_language_database(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            previous = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                root = Path(tempdir)
                german = ReviewTask(1, "de", "Guten Tag.", "Hello.", [], {})
                russian = ReviewTask(2, "ru", "Добрый день.", "Hello.", [], {})
                toggle_favorite_sentence(root / "german.db", german)
                toggle_favorite_sentence(root / "russian.db", russian)

                filtered = favorite_sentences(root / "russian.db", "rus")

                self.assertEqual([item["text"] for item in filtered], ["Добрый день."])
            finally:
                if previous is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = previous
