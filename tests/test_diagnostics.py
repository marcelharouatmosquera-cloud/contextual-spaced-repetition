from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from contextual_review.corpus import initialize_database, insert_sentence
from contextual_review.diagnostics import DiagnosticCheck, DiagnosticReport, collect_diagnostics, format_diagnostics
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
    def __init__(self, card_ids=None, scheduler=None):
        self.sched = scheduler if scheduler is not None else FakeScheduler()
        self.decks = FakeDecks()
        self.card_ids = list(card_ids or [])

    def find_cards(self, query: str):
        return list(self.card_ids)


class FakeMw:
    def __init__(self, config, card_ids=None, scheduler=None, taskman=None, checkpoint=True):
        self.addonManager = FakeAddonManager(config)
        self.col = FakeCollection(card_ids=card_ids, scheduler=scheduler)
        self.taskman = taskman
        if checkpoint:
            self.checkpoint = lambda name: None


class FakeTaskman:
    def run_in_background(self, work, done) -> None:
        pass


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
