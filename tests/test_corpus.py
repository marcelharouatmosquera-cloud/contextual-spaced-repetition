from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextual_review.corpus import (
    _candidate_sort_key,
    build_expanded_match_query,
    connect_database,
    delete_sentences_for_language,
    initialize_database,
    insert_sentence,
    open_review_database,
    sentence_count_for_language,
    select_review_task,
    SENTENCE_FORMS_BACKFILL_KEY,
    upsert_word_forms,
    WORD_FORMS_BACKFILL_KEY,
)
from contextual_review.types import DueCard, SentenceCandidate
from contextual_review.importer import sentence_word_map


class CorpusTests(unittest.TestCase):
    def test_language_library_count_and_partial_or_full_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            conn = connect_database(db_path)
            try:
                for text in ("One useful example.", "Two useful examples.", "Three useful examples."):
                    insert_sentence(conn, "en", text, None, sentence_word_map(text, "en"))
                insert_sentence(
                    conn,
                    "de",
                    "Ein gutes Beispiel.",
                    None,
                    sentence_word_map("Ein gutes Beispiel.", "de"),
                )
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(sentence_count_for_language(db_path, "eng"), 3)
            self.assertEqual(delete_sentences_for_language(db_path, "en", 2), 2)
            self.assertEqual(sentence_count_for_language(db_path, "en"), 1)
            self.assertEqual(sentence_count_for_language(db_path, "de"), 1)
            self.assertEqual(delete_sentences_for_language(db_path, "en"), 1)
            self.assertEqual(sentence_count_for_language(db_path, "en"), 0)
    def test_new_schema_omits_unused_sentence_lemma_index(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                table_names = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                conn.close()

            self.assertNotIn("sentence_lemmas", table_names)
            self.assertNotIn("word_map", table_names)

    def test_build_expanded_match_query_uses_wildcard_prefix_terms(self) -> None:
        self.assertEqual(
            build_expanded_match_query([("eat", False), ("comput", True)]),
            '"eat" OR comput*',
        )

    def test_insert_sentence_duplicate_with_plain_sqlite_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                first = insert_sentence(conn, "en", "We review daily.", None)
                duplicate = insert_sentence(conn, "en", "We review daily.", None)
                conn.commit()
            finally:
                conn.close()

            self.assertEqual(duplicate, first)

    def test_review_connection_is_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)

            conn = open_review_database(db_path)
            try:
                with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
                    conn.execute(
                        "INSERT INTO sentences(language, full_text) VALUES ('en', 'No writes.')"
                    )
            finally:
                conn.close()

    def test_review_selection_never_runs_schema_migrations(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "en", "We review daily.", None)
                conn.execute("DELETE FROM corpus_meta")
                conn.commit()
            finally:
                conn.close()

            with patch(
                "contextual_review.corpus.ensure_database_schema",
                side_effect=AssertionError("review attempted a schema migration"),
            ):
                task = select_review_task(
                    db_path,
                    [DueCard(card_id=1, target_word="review", lemma="review", word_form="review")],
                    "en",
                    set(),
                    10,
                    matching_mode="exact_form",
                )

            self.assertIsNotNone(task)

    def test_select_review_task_prefers_more_matched_cards(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "en", "We review daily.", None)
                insert_sentence(
                    conn,
                    "en",
                    "We review word cards.",
                    None,
                )
                conn.commit()
            finally:
                conn.close()

            due = [
                DueCard(card_id=1, target_word="review", lemma="review", definition="revise", overdue=0),
                DueCard(card_id=2, target_word="word", lemma="word", definition="term", overdue=0),
            ]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "We review word cards.")
            self.assertEqual(task.card_ids_by_key["review"], [1])
            self.assertEqual(task.card_ids_by_key["word"], [2])
            self.assertEqual(
                [(item.target_word, item.definition) for item in task.target_words],
                [("review", "revise"), ("word", "term")],
            )

    def test_select_review_task_prefers_coverage_before_overdue_priority(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "en", "Review now.", None)
                insert_sentence(conn, "en", "Learn word cards.", None)
                conn.commit()
            finally:
                conn.close()

            due = [
                DueCard(card_id=1, target_word="review", lemma="review", priority=100.0),
                DueCard(card_id=2, target_word="word", lemma="word", priority=1.0),
                DueCard(card_id=3, target_word="card", lemma="card", priority=1.0),
            ]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "Learn word cards.")

    def test_select_review_task_excludes_shown_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                first = insert_sentence(conn, "en", "We review words.", None)
                insert_sentence(conn, "en", "Cards help review.", None)
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=1, target_word="review", lemma="review", overdue=0)]
            task = select_review_task(db_path, due, "en", {first}, 10)

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "Cards help review.")

    def test_select_review_task_soft_avoidance_falls_back_without_second_query(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                first = insert_sentence(
                    conn,
                    "en",
                    "One review sentence.",
                    None,
                )
                second = insert_sentence(
                    conn,
                    "en",
                    "Two review examples.",
                    None,
                )
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=1, target_word="review", lemma="review", word_form="review")]
            task = select_review_task(
                db_path,
                due,
                "en",
                set(),
                10,
                matching_mode="exact_form",
                soft_avoid_sentence_ids={first},
            )

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.sentence_id, second)

    def test_select_review_task_uses_sentence_word_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(
                    conn,
                    "en",
                    "Students study daily.",
                    None,
                    {"students": "student", "study": "study"},
                )
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=1, target_word="students", lemma="students", word_form="students")]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.card_ids_by_key["student"], [1])

    def test_exact_form_mode_does_not_match_inflected_lemma_family(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(
                    conn,
                    "de",
                    "Ich sehe Hunde.",
                    None,
                    {"ich": "ich", "sehe": "seh", "hunde": "hund"},
                )
                insert_sentence(
                    conn,
                    "de",
                    "Der Hund schlaft.",
                    None,
                    {"der": "der", "hund": "hund", "schlaft": "schlaft"},
                )
                conn.commit()
            finally:
                conn.close()

            due = [
                DueCard(
                    card_id=1,
                    target_word="Hund",
                    lemma="hund",
                    word_form="hund",
                    match_key="hund",
                )
            ]
            task = select_review_task(db_path, due, "de", set(), 10, matching_mode="exact_form")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "Der Hund schlaft.")
            self.assertEqual(task.card_ids_by_key["hund"], [1])

    def test_lemma_family_expands_word_forms_and_maps_token_to_base_card(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(
                    conn,
                    "en",
                    "She went, home.",
                    None,
                    {"she": "she", "went": "go", "home": "home"},
                )
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=12345, target_word="go", lemma="go", word_form="go")]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "She went, home.")
            went = next(token for token in task.tokens if token.text == "went")
            self.assertTrue(went.is_target)
            self.assertEqual(went.match_key, "go")
            self.assertEqual(went.card_ids, (12345,))
            self.assertEqual(task.card_ids_by_key["go"], [12345])

    def test_lemma_family_falls_back_to_fts_prefix_when_form_table_has_no_word(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "en", "Computing feels useful.", None)
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=7, target_word="comput", lemma="comput", word_form="comput")]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            computing = next(token for token in task.tokens if token.text == "Computing")
            self.assertTrue(computing.is_target)
            self.assertEqual(computing.match_key, "comput")
            self.assertEqual(computing.card_ids, (7,))

    def test_word_forms_can_be_imported_without_sentence_word_map(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "en", "They ran outside.", None)
                upsert_word_forms(conn, {"ran": "run", "run": "run"})
                conn.commit()
            finally:
                conn.close()

            due = [DueCard(card_id=9, target_word="run", lemma="run", word_form="run")]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="lemma_family")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "They ran outside.")

    def test_writable_connect_repairs_missing_sentence_form_index_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    INSERT INTO sentences(language, full_text, translation, word_count, source, quality_flags)
                    VALUES ('en', 'We repair indexes.', NULL, 3, 'test', '')
                    """
                )
                conn.execute("DELETE FROM corpus_meta WHERE key = ?", (SENTENCE_FORMS_BACKFILL_KEY,))
                conn.commit()
            finally:
                conn.close()

            repaired_connection = connect_database(db_path)
            repaired_connection.close()

            due = [DueCard(card_id=77, target_word="repair", lemma="repair", word_form="repair")]
            task = select_review_task(db_path, due, "en", set(), 10, matching_mode="exact_form")

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, "We repair indexes.")

            conn = sqlite3.connect(str(db_path))
            try:
                repaired = conn.execute(
                    "SELECT COUNT(*) FROM sentence_forms WHERE CAST(sentence_id AS INTEGER) = ?",
                    (task.sentence_id,),
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(repaired, 1)

    def test_schema_repair_finds_missing_form_row_even_when_another_is_duplicated(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                first = insert_sentence(conn, "en", "Cards help daily.", None)
                second = insert_sentence(
                    conn,
                    "en",
                    "We repair indexes.",
                    None,
                )
                conn.execute("DELETE FROM sentence_forms WHERE sentence_id = ?", (second,))
                first_forms = conn.execute(
                    "SELECT word_form_list FROM sentence_forms WHERE sentence_id = ?",
                    (first,),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO sentence_forms(sentence_id, word_form_list) VALUES (?, ?)",
                    (first, first_forms),
                )
                conn.execute("DELETE FROM corpus_meta WHERE key = ?", (SENTENCE_FORMS_BACKFILL_KEY,))
                conn.commit()
            finally:
                conn.close()

            repaired_connection = connect_database(db_path)
            repaired_connection.close()

            task = select_review_task(
                db_path,
                [DueCard(card_id=77, target_word="repair", lemma="repair", word_form="repair")],
                "en",
                set(),
                10,
                matching_mode="exact_form",
            )

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.sentence_id, second)

    def test_schema_repair_backfills_all_missing_word_form_mappings(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    "CREATE TABLE word_map(word_form TEXT PRIMARY KEY, lemma TEXT NOT NULL)"
                )
                conn.execute("INSERT INTO word_map(word_form, lemma) VALUES ('went', 'go')")
                conn.execute("INSERT INTO word_forms(form, base) VALUES ('dogs', 'dog')")
                conn.execute("DELETE FROM corpus_meta WHERE key = ?", (WORD_FORMS_BACKFILL_KEY,))
                conn.commit()
            finally:
                conn.close()

            repaired = connect_database(db_path)
            repaired.close()

            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute(
                        "SELECT base FROM word_forms WHERE form = 'went'"
                    ).fetchone()[0],
                    "go",
                )
            finally:
                conn.close()

    def test_japanese_target_matches_inside_unsegmented_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "sentences.db"
            initialize_database(db_path)
            import sqlite3

            sentence = "\u732b\u304c\u9b5a\u3092\u98df\u3079\u308b\u3002"
            target = "\u98df\u3079\u308b"
            word_map = sentence_word_map(sentence, "ja")
            conn = sqlite3.connect(str(db_path))
            try:
                insert_sentence(conn, "ja", sentence, None, word_map)
                conn.commit()
            finally:
                conn.close()

            due = [
                DueCard(
                    card_id=88,
                    target_word=target,
                    lemma=target,
                    word_form=target,
                    match_key=target,
                )
            ]
            task = select_review_task(
                db_path,
                due,
                "ja",
                set(),
                10,
                min_sentence_words=2,
                max_sentence_words=10,
                matching_mode="exact_form",
            )

            self.assertIsNotNone(task)
            assert task is not None
            self.assertEqual(task.full_text, sentence)
            matched = next(token for token in task.tokens if token.is_target)
            self.assertEqual(matched.text, target)
            self.assertEqual(matched.card_ids, (88,))

    def test_candidate_sort_key_uses_bm25_then_shorter_sentence_for_ties(self) -> None:
        base = dict(
            sentence_id=1,
            language="en",
            full_text="Review.",
            translation=None,
            matched_lemmas=["review"],
            score=10.0,
            matched_card_count=1,
        )
        stronger_bm25 = SentenceCandidate(**base, bm25_score=-1.0, word_count=4)
        weaker_bm25 = SentenceCandidate(**{**base, "sentence_id": 2}, bm25_score=0.0, word_count=1)
        shorter = SentenceCandidate(**{**base, "sentence_id": 3}, bm25_score=-1.0, word_count=2)

        ordered = sorted([weaker_bm25, stronger_bm25, shorter], key=_candidate_sort_key)

        self.assertEqual([candidate.sentence_id for candidate in ordered], [3, 1, 2])

    def test_candidate_sort_key_prefers_stored_translation_before_bm25_tie_breaks(self) -> None:
        base = dict(
            language="en",
            full_text="Review.",
            matched_lemmas=["review"],
            score=10.0,
            matched_card_count=1,
            word_count=3,
        )
        translated = SentenceCandidate(
            **{**base, "sentence_id": 1},
            translation="Translated.",
            bm25_score=0.0,
        )
        untranslated = SentenceCandidate(
            **{**base, "sentence_id": 2},
            translation=None,
            bm25_score=-1.0,
        )

        ordered = sorted([untranslated, translated], key=_candidate_sort_key)

        self.assertEqual([candidate.sentence_id for candidate in ordered], [1, 2])


if __name__ == "__main__":
    unittest.main()
