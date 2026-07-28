from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from contextual_review.corpus import initialize_database, insert_sentence
from contextual_review.config import normalize_config
from contextual_review.diagnostics import (
    DiagnosticCheck,
    DiagnosticReport,
    _card_direction_check,
    _config_check,
    collect_diagnostics,
    format_diagnostics,
)
from contextual_review.importer import sentence_word_map


class FakeAddonManager:
    def __init__(self, config):
        self.config = config

    def getConfig(self, addon_name: str):
        return dict(self.config)


class FakeScheduler:
    today = 100

    def answerCard(self, card, ease: int) -> None:
        pass


class FakeDecks:
    def selected(self) -> int:
        return 1

    def get(self, deck_id: int):
        return {"name": "Vocabulary"}


class FakeCollection:
    def __init__(self, card_ids=None, scheduler=None, cards=None):
        self.sched = scheduler if scheduler is not None else FakeScheduler()
        self.decks = FakeDecks()
        self.card_ids = list(card_ids or [])
        self.cards = dict(cards or {})

    def find_cards(self, query: str):
        return list(self.card_ids)

    def get_card(self, card_id: int):
        return self.cards[int(card_id)]


class FakeMw:
    def __init__(
        self,
        config,
        card_ids=None,
        scheduler=None,
        taskman=None,
        checkpoint=True,
        cards=None,
    ):
        self.addonManager = FakeAddonManager(config)
        self.col = FakeCollection(card_ids=card_ids, scheduler=scheduler, cards=cards)
        self.taskman = taskman
        if checkpoint:
            self.checkpoint = lambda name: None


class FakeTaskman:
    def run_in_background(self, work, done) -> None:
        pass


class DirectionNote:
    def __init__(self, templates):
        self.templates = templates

    def keys(self):
        return ["German", "English"]

    def __getitem__(self, key: str):
        return {"German": "Hund", "English": "dog"}[key]

    def note_type(self):
        return {"name": "Language", "tmpls": self.templates}

    def model(self):
        return self.note_type()


class DirectionCard:
    def __init__(self, card_id: int, note: DirectionNote, ordinal: int):
        self.id = card_id
        self._note = note
        self.ord = ordinal

    def note(self):
        return self._note


class DiagnosticsTests(unittest.TestCase):
    def test_collect_diagnostics_ok_for_ready_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "context.db"
            _build_db(db_path)
            mw = FakeMw(
                {"database_path": str(db_path), "language": "en"},
                card_ids=[1, 2],
                taskman=FakeTaskman(),
            )

            report = collect_diagnostics(mw, "addon")
            text = format_diagnostics(report)

            self.assertTrue(report.ok)
            self.assertIn("[OK] Corpus database", text)
            self.assertIn("word-form mappings", text)
            self.assertIn("[OK] Scheduler", text)
            self.assertIn("query returned 2 card", text)

    def test_collect_diagnostics_reports_missing_database_and_scheduler(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "missing.db"
            mw = FakeMw(
                {"database_path": str(db_path), "language": "en"},
                scheduler=object(),
                checkpoint=False,
            )

            report = collect_diagnostics(mw, "addon")
            text = format_diagnostics(report)

            self.assertFalse(report.ok)
            self.assertIn("missing at", text)
            self.assertIn("answerCard/answer_card unavailable", text)
            self.assertIn("mw.checkpoint unavailable", text)

    def test_report_with_warning_needs_attention_without_error(self) -> None:
        report = DiagnosticReport([DiagnosticCheck("Due search", "warning", "query returned no cards")])

        self.assertTrue(report.ok)
        self.assertTrue(report.has_warnings)
        self.assertTrue(report.needs_attention)

    def test_config_check_warns_when_translation_field_is_the_target_field(self) -> None:
        config = normalize_config(
            {"target_field": "German", "dictionary_field": " german "}
        )

        check = _config_check(config)

        self.assertEqual(check.status, "warning")
        self.assertIn("target and translation fields are identical", check.detail)

    def test_collect_diagnostics_reports_invalid_relative_database_path(self) -> None:
        mw = FakeMw({"database_path": "../outside.db", "language": "en"})

        report = collect_diagnostics(mw, "addon")
        text = format_diagnostics(report)

        self.assertFalse(report.ok)
        self.assertIn("[ERROR] Corpus database: invalid path", text)
        self.assertIn("Relative database paths", text)

    def test_collect_diagnostics_reports_incomplete_sentence_index(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "context.db"
            _build_db(db_path)
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute("DELETE FROM sentence_forms")
                conn.commit()
            finally:
                conn.close()
            mw = FakeMw({"database_path": str(db_path), "language": "en"})

            report = collect_diagnostics(mw, "addon")
            text = format_diagnostics(report)

            self.assertTrue(report.ok)
            self.assertTrue(report.needs_attention)
            self.assertIn("sentences but 0 form-index rows", text)

    def test_card_direction_check_accepts_configured_recognition_and_recall(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{German}}", "afmt": "{{English}}"},
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{German}}"},
        ]
        note = DirectionNote(templates)
        cards = {
            1: DirectionCard(1, note, 0),
            2: DirectionCard(2, note, 1),
        }
        mw = FakeMw({}, card_ids=[1, 2], cards=cards)
        config = normalize_config(
            {
                "target_field": "German",
                "dictionary_field": "English",
                "included_card_templates": ["Recognition"],
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
            }
        )

        check = _card_direction_check(mw, config)

        self.assertEqual(check.status, "ok")
        self.assertIn("recognition=1", check.detail)
        self.assertIn("recall=1", check.detail)
        self.assertIn("invalid recognition=0", check.detail)
        self.assertIn("recall templates=Recall", check.detail)

    def test_card_direction_check_warns_for_unmapped_reverse_card(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{German}}", "afmt": "{{English}}"},
            {"name": "Reverse", "qfmt": "{{English}}", "afmt": "{{German}}"},
        ]
        note = DirectionNote(templates)
        cards = {
            1: DirectionCard(1, note, 0),
            2: DirectionCard(2, note, 1),
        }
        mw = FakeMw({}, card_ids=[1, 2], cards=cards)
        config = normalize_config(
            {
                "target_field": "German",
                "dictionary_field": "English",
                "custom_search_query": "is:due",
            }
        )

        check = _card_direction_check(mw, config)

        self.assertEqual(check.status, "warning")
        self.assertIn("recognition=1", check.detail)
        self.assertIn("recall=0", check.detail)
        self.assertIn("invalid recognition=1", check.detail)

    def test_card_direction_check_warns_for_recall_template_without_native_front(self) -> None:
        templates = [
            {"name": "Recall", "qfmt": "{{Picture}}", "afmt": "{{German}}"},
        ]
        note = DirectionNote(templates)
        cards = {1: DirectionCard(1, note, 0)}
        mw = FakeMw({}, card_ids=[1], cards=cards)
        config = normalize_config(
            {
                "target_field": "German",
                "dictionary_field": "English",
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
            }
        )

        check = _card_direction_check(mw, config)

        self.assertEqual(check.status, "warning")
        self.assertIn("recall=0", check.detail)
        self.assertIn("invalid recall=1", check.detail)


def _build_db(db_path: Path) -> None:
    initialize_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        text = "We review cards daily."
        word_map = sentence_word_map(text, "en")
        insert_sentence(conn, "en", text, text, word_map)
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    unittest.main()
