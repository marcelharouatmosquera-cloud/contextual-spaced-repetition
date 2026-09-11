from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from contextual_review.config import USER_ROOT_ENV
from contextual_review.corpus import connect_database, insert_sentence
from contextual_review.dialogs import _sentence_details_html, recent_sentence_records
from contextual_review.reviewer import _remember_recent_sentence_id


class RecentSentenceTests(unittest.TestCase):
    def test_sentence_details_escape_saved_content(self) -> None:
        html = _sentence_details_html(
            {"text": "<word>", "translation": "A & B"},
            "<p>Trusted details</p>",
        )

        self.assertIn("&lt;word&gt;", html)
        self.assertIn("A &amp; B", html)
        self.assertIn("<p>Trusted details</p>", html)

    def test_corrupt_history_is_preserved_before_a_clean_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            previous = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                state_path = Path(tempdir) / "user_files" / "recent_sentence_history.json"
                state_path.parent.mkdir(parents=True)
                state_path.write_text("not JSON", encoding="utf-8")

                self.assertEqual(
                    _remember_recent_sentence_id(Path(tempdir) / "sentences.db", "de", 17),
                    {17},
                )

                backups = list(state_path.parent.glob("recent_sentence_history.json.corrupt-*"))
                self.assertEqual(len(backups), 1)
                self.assertEqual(backups[0].read_text(encoding="utf-8"), "not JSON")
                histories = json.loads(state_path.read_text(encoding="utf-8"))["histories"]
                self.assertIn(17, next(iter(histories.values())))
            finally:
                if previous is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = previous

    def test_records_are_newest_first_and_limited_to_current_database(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            previous = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                database_path = Path(tempdir) / "sentences.db"
                conn = connect_database(database_path)
                try:
                    first = insert_sentence(
                        conn,
                        "de",
                        "Der Hund schläft.",
                        "The dog sleeps.",
                        source="test corpus",
                    )
                    second = insert_sentence(
                        conn,
                        "de",
                        "Die Katze wartet.",
                        "The cat waits.",
                    )
                    conn.commit()
                finally:
                    conn.close()

                _remember_recent_sentence_id(database_path, "de", first)
                _remember_recent_sentence_id(database_path, "de", second)
                _remember_recent_sentence_id(database_path, "de", first)

                records = recent_sentence_records(database_path, "de", limit=100)
            finally:
                if previous is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = previous

        self.assertEqual(
            [record["sentence_id"] for record in records],
            [first, second],
        )
        self.assertEqual(records[0]["translation"], "The dog sleeps.")
        self.assertEqual(records[0]["source"], "test corpus")


if __name__ == "__main__":
    unittest.main()
