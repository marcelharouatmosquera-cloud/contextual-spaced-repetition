from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from contextual_review.config import USER_ROOT_ENV
from contextual_review.corpus import connect_database, insert_sentence
from contextual_review.dialogs import recent_sentence_records
from contextual_review.reviewer import _remember_recent_sentence_id


class RecentSentenceTests(unittest.TestCase):
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
