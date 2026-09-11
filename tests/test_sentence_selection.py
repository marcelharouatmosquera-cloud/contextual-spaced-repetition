"""Regression scenarios for useful multi-card contextual reviews."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from contextual_review.corpus import connect_database, insert_sentence, select_review_task
from contextual_review.types import DueCard


class SentenceSelectionTests(unittest.TestCase):
    def test_unusable_hits_do_not_hide_valid_examples(self) -> None:
        # Exercise spaced FTS, one-character scan, two-character ngram lookup,
        # and trigram FTS. Keep the candidate pool deliberately small.
        for language, target in (("en", "anchor"), ("ja", "猫"), ("ja", "食事"), ("ko", "공부하")):
            for reason in ("short", "long", "shown", "legacy_counts"):
                with self.subTest(language=language, target=target, reason=reason):
                    with tempfile.TemporaryDirectory() as directory:
                        path = Path(directory) / "corpus.db"
                        conn = connect_database(path)
                        shown = set()
                        try:
                            for index in range(35):
                                if reason in {"short", "legacy_counts"}:
                                    sentence = f"{target} {index}."
                                elif reason == "long":
                                    sentence = f"{target} alpha beta gamma delta epsilon zeta eta theta {index}."
                                else:
                                    sentence = f"{target} alpha beta item{index}."
                                sentence_id = insert_sentence(conn, language, sentence, None)
                                if reason == "shown":
                                    shown.add(sentence_id)
                            expected = f"{target} alpha beta final."
                            insert_sentence(conn, language, expected, None)
                            if reason == "legacy_counts":
                                conn.execute("UPDATE sentences SET word_count = 0")
                            conn.commit()
                        finally:
                            conn.close()

                        task = select_review_task(
                            path, [DueCard(1, target, target)], language, shown, 1,
                            min_sentence_words=4, max_sentence_words=6,
                        )
                        self.assertIsNotNone(task)
                        self.assertEqual(task.full_text, expected)
                        self.assertEqual({c.card_id for c in task.target_words}, {1})

    def _select(self, sentences, cards):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.db"
            conn = connect_database(path)
            try:
                for sentence in sentences:
                    insert_sentence(conn, "en", sentence, None)
                conn.commit()
            finally:
                conn.close()
            task = select_review_task(path, cards, "en", set(), 10)
            self.assertIsNotNone(task)
            return task

    def test_due_coverage_beats_more_optional_early_reviews(self) -> None:
        task = self._select(
            ["Anchor companion today.", "Anchor future distant tomorrow."],
            [
                DueCard(1, "anchor", "anchor", priority=100),
                DueCard(2, "companion", "companion"),
                DueCard(3, "future", "future", due_in_days=1),
                DueCard(4, "distant", "distant", due_in_days=7),
                DueCard(5, "tomorrow", "tomorrow", due_in_days=1),
            ],
        )
        self.assertEqual(task.full_text, "Anchor companion today.")
        self.assertEqual({c.card_id for c in task.target_words}, {1, 2})

    def test_future_priority_cannot_displace_a_currently_due_anchor(self) -> None:
        task = self._select(
            ["Anchor today.", "Future tomorrow."],
            [DueCard(1, "anchor", "anchor"), DueCard(2, "future", "future", priority=500, due_in_days=1)],
        )
        self.assertEqual(task.full_text, "Anchor today.")

    def test_optional_early_reviews_remain_available_when_nothing_is_due(self) -> None:
        task = self._select(
            ["Future tomorrow.", "Distant later."],
            [DueCard(1, "future", "future", due_in_days=1), DueCard(2, "distant", "distant", due_in_days=7)],
        )
        self.assertEqual(task.full_text, "Future tomorrow.")

    def test_equal_coverage_prefers_nearer_early_review(self) -> None:
        task = self._select(
            ["Anchor distant.", "Anchor future."],
            [
                DueCard(1, "anchor", "anchor", priority=100),
                DueCard(2, "future", "future", due_in_days=1),
                DueCard(3, "distant", "distant", due_in_days=7),
            ],
        )
        self.assertEqual(task.full_text, "Anchor future.")

    def test_multiword_card_does_not_get_duplicate_urgency_credit(self) -> None:
        task = self._select(
            ["Anchor red blue.", "Anchor companion here."],
            [
                DueCard(1, "anchor", "anchor", priority=100),
                DueCard(2, "red blue", "red", match_key="red", priority=10),
                DueCard(2, "red blue", "blue", match_key="blue", priority=10),
                DueCard(3, "companion", "companion", priority=15),
            ],
        )
        self.assertEqual(task.full_text, "Anchor companion here.")

    def test_future_hits_cannot_fill_pool_before_due_companion_is_searched(self) -> None:
        task = self._select(
            [f"Anchor future {index}." for index in range(35)]
            + [f"Companion elsewhere {index}." for index in range(200)]
            + ["The anchor and companion appear together here."],
            [DueCard(1, "anchor", "anchor", priority=100),
             DueCard(2, "companion", "companion"),
             DueCard(3, "future", "future", due_in_days=1)],
        )
        self.assertEqual({c.card_id for c in task.target_words}, {1, 2})

    def test_stale_index_cannot_grade_a_word_missing_from_the_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.db"
            conn = connect_database(path)
            try:
                bad = insert_sentence(conn, "en", "Nothing relevant here.", None)
                conn.execute("UPDATE sentence_forms SET word_form_list = 'anchor' WHERE sentence_id = ?", (bad,))
                insert_sentence(conn, "en", "We use the anchor safely.", None)
                conn.commit()
            finally:
                conn.close()
            task = select_review_task(path, [DueCard(1, "anchor", "anchor")], "en", set(), 10)
            self.assertIsNotNone(task)
            self.assertEqual(task.full_text, "We use the anchor safely.")
            self.assertTrue(any(t.is_target and 1 in t.card_ids for t in task.tokens))

    def test_missing_visible_anchor_falls_back_without_grading_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.db"
            conn = connect_database(path)
            try:
                bad = insert_sentence(conn, "en", "Nothing relevant here.", None)
                conn.execute("UPDATE sentence_forms SET word_form_list = 'anchor' WHERE sentence_id = ?", (bad,))
                insert_sentence(conn, "en", "Companion here.", None)
                conn.commit()
            finally:
                conn.close()
            anchor = DueCard(1, "anchor", "anchor", priority=100)
            self.assertIsNone(select_review_task(path, [anchor], "en", set(), 10))
            task = select_review_task(
                path, [anchor, DueCard(2, "companion", "companion")], "en", set(), 10,
            )
            self.assertEqual({c.card_id for c in task.target_words}, {2})


if __name__ == "__main__":
    unittest.main()
