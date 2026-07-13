from __future__ import annotations

import unittest
import tempfile
import inspect
from pathlib import Path
from types import SimpleNamespace

from contextual_review.dialogs import (
    INSTRUCTIONS_HTML,
    INSTRUCTIONS_TEXT,
    SENTENCE_FILE_FILTER,
    WORD_FORMS_FILE_FILTER,
    _corpus_import_done_message,
    _basic_solution_fields,
    _open_settings_editor_dialog,
    _tatoeba_import_done_message,
    _word_forms_import_done_message,
    delete_sentence_registry_file,
)
from contextual_review.config import normalize_config
from contextual_review.web import render_message_html


class OnboardingTextTests(unittest.TestCase):
    def test_settings_use_basic_and_advanced_progressive_disclosure(self) -> None:
        source = inspect.getsource(_open_settings_editor_dialog)

        self.assertIn('tabs.addTab(basic_tab, "Basic Setup")', source)
        self.assertIn('tabs.addTab(advanced_tab, "Advanced / Nerd Settings")', source)
        self.assertIn("Which field is the target word?", source)
        self.assertIn("Which field is the translation?", source)
        self.assertIn("Preview Auto-Configure", source)
        self.assertIn("production cards are excluded", source)
        self.assertIn("Review Due Cards", source)
        self.assertIn("Learn New Cards", source)
        self.assertIn("Recommended: 100,000 to 200,000 sentences.", source)
        self.assertIn("only a few MB", source)
        self.assertNotIn(chr(0x2014), source)

    def test_basic_field_mapping_keeps_advanced_solution_fields(self) -> None:
        config = normalize_config(
            {
                "dictionary_field": "English",
                "solution_fields": [
                    {"field": "English", "display": "text"},
                    {"field": "Audio", "display": "audio", "autoplay": True},
                    {"field": "Picture", "display": "image"},
                ],
            }
        )

        translation, audio, extras = _basic_solution_fields(config)

        self.assertEqual(translation.field, "English")
        self.assertEqual(audio.field, "Audio")
        self.assertEqual([item.field for item in extras], ["Picture"])

    def test_instructions_explain_real_review_flow(self) -> None:
        self.assertIn("Click only the words you did not remember", INSTRUCTIONS_TEXT)
        self.assertIn("Show Solution", INSTRUCTIONS_TEXT)
        self.assertIn("Grade & Next", INSTRUCTIONS_TEXT)
        self.assertIn("Again", INSTRUCTIONS_TEXT)
        self.assertIn("Good", INSTRUCTIONS_TEXT)

    def test_instructions_explain_deck_safety_and_submission_boundary(self) -> None:
        self.assertIn("does not create, move, edit, or delete your decks or notes", INSTRUCTIONS_TEXT)
        self.assertIn("choose the deck you want to configure", INSTRUCTIONS_TEXT)
        self.assertIn("Cards are scheduled only when you press Grade & Next", INSTRUCTIONS_TEXT)
        self.assertIn("Ctrl+Z immediately undoes", INSTRUCTIONS_TEXT)
        self.assertIn("Safe to explore", INSTRUCTIONS_HTML)

    def test_instructions_explain_file_sources_and_word_forms(self) -> None:
        self.assertIn("Sentence Library", INSTRUCTIONS_TEXT)
        self.assertIn("Advanced settings can import .txt, .srt, .tsv, .csv, and .bz2", INSTRUCTIONS_TEXT)
        self.assertIn("went\tgo", INSTRUCTIONS_TEXT)
        self.assertIn("Import Word Forms", INSTRUCTIONS_TEXT)

    def test_file_dialog_filters_name_supported_formats(self) -> None:
        for extension in (".txt", ".srt", ".tsv", ".csv", ".bz2"):
            self.assertIn(extension, SENTENCE_FILE_FILTER)
        for extension in (".tsv", ".csv", ".txt"):
            self.assertIn(extension, WORD_FORMS_FILE_FILTER)

    def test_import_done_messages_give_next_steps(self) -> None:
        result = SimpleNamespace(inserted=3, skipped=1, database_path=Path("context.db"))

        self.assertIn("Diagnostics", _corpus_import_done_message(result))
        self.assertIn("Lemma family", _word_forms_import_done_message(result))

    def test_zero_import_messages_explain_how_to_recover(self) -> None:
        result = SimpleNamespace(inserted=0, skipped=5, database_path=Path("context.db"))

        self.assertIn("supported format", _corpus_import_done_message(result))
        self.assertIn("language code", _tatoeba_import_done_message(result))
        self.assertIn("two columns", _word_forms_import_done_message(result))

    def test_missing_database_message_can_link_to_setup_action(self) -> None:
        html = render_message_html(
            "Sentence database missing",
            "Open Contextual Review Settings and use the Sentence Library section.",
            action_label="Open Settings",
            action="settings",
        )

        self.assertIn("Open Settings", html)
        self.assertIn("Sentence Library", html)

    def test_delete_sentence_registry_file_removes_configured_database(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            db_path = Path(tempdir) / "context.db"
            db_path.write_text("temporary registry", encoding="utf-8")
            db_path.with_name(db_path.name + "-wal").write_text("wal", encoding="utf-8")
            db_path.with_name(db_path.name + "-shm").write_text("shm", encoding="utf-8")
            config = normalize_config({"database_path": str(db_path)})

            removed_path, removed = delete_sentence_registry_file(config)

            self.assertEqual(removed_path, db_path)
            self.assertTrue(removed)
            self.assertFalse(db_path.exists())
            self.assertFalse(db_path.with_name(db_path.name + "-wal").exists())
            self.assertFalse(db_path.with_name(db_path.name + "-shm").exists())

    def test_delete_sentence_registry_refuses_non_database_path(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "notes.txt"
            path.write_text("not a database", encoding="utf-8")
            config = normalize_config({"database_path": str(path)})

            with self.assertRaisesRegex(RuntimeError, "does not look like a SQLite database"):
                delete_sentence_registry_file(config)

            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main()
