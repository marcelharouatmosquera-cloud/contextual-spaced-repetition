from __future__ import annotations

import tempfile
import unittest
import os
from pathlib import Path

from contextual_review import config as config_module
from contextual_review.config import (
    DEFAULT_CUSTOM_SEARCH_QUERY,
    DEFAULT_DATABASE_PATH,
    USER_ROOT_ENV,
    load_config,
    normalize_config,
    resolve_database_path,
    upsert_deck_config,
)


class FakeAddonManager:
    def __init__(self, config):
        self.config = config
        self.written = None

    def getConfig(self, addon_name: str):
        return dict(self.config)

    def writeConfig(self, addon_name: str, config):
        self.written = (addon_name, dict(config))


class FakeMw:
    def __init__(self, config):
        self.addonManager = FakeAddonManager(config)


class ConfigTests(unittest.TestCase):
    def test_default_custom_search_query_excludes_reverse_cards(self) -> None:
        config = normalize_config({})

        self.assertEqual(config.custom_search_query, DEFAULT_CUSTOM_SEARCH_QUERY)

    def test_beginner_defaults_use_lemma_matching_and_readable_sentences(self) -> None:
        config = normalize_config({})

        self.assertEqual(config.matching_mode, "lemma_family")
        self.assertEqual((config.min_sentence_words, config.max_sentence_words), (4, 15))
        self.assertTrue(config.include_due_cards)
        self.assertFalse(config.include_new_cards)
        self.assertEqual(config.max_new_cards, 10)

    def test_load_config_migrates_legacy_search_query(self) -> None:
        mw = FakeMw({"search_query": "is:due deck:Russian"})

        config = load_config(mw, "addon")

        self.assertEqual(config.custom_search_query, "is:due deck:Russian")

    def test_load_config_migrates_legacy_dictionary_field_to_solution_fields(self) -> None:
        mw = FakeMw({"dictionary_field": "Definition"})

        config = load_config(mw, "addon")

        self.assertEqual([field.field for field in config.solution_fields], ["Definition"])

    def test_sentence_word_bounds_are_sorted(self) -> None:
        config = normalize_config({"min_sentence_words": 12, "max_sentence_words": 3})

        self.assertEqual(config.min_sentence_words, 3)
        self.assertEqual(config.max_sentence_words, 12)

    def test_dictionary_and_native_language_defaults(self) -> None:
        config = normalize_config({})

        self.assertEqual(config.dictionary_field, "Back")
        self.assertEqual([field.field for field in config.solution_fields], ["Back"])
        self.assertEqual(config.native_language, "en")

    def test_solution_fields_accept_structured_rows_and_keep_legacy_fallback(self) -> None:
        config = normalize_config(
            {
                "dictionary_field": "Definition",
                "solution_fields": [
                    {"field": "Reading", "label": "Kana", "display": "text"},
                    {"field": "Audio", "display": "audio", "autoplay": True},
                ],
            }
        )

        self.assertEqual(
            [
                (field.field, field.label, field.display, field.autoplay)
                for field in config.solution_fields
            ],
            [
                ("Reading", "Kana", "text", False),
                ("Audio", "", "audio", True),
            ],
        )

        migrated = normalize_config({"dictionary_field": "Definition", "solution_fields": []})
        self.assertEqual([field.field for field in migrated.solution_fields], ["Definition"])

        merged_defaults = normalize_config(
            {
                "dictionary_field": "Definition",
                "solution_fields": [
                    {"field": "Back", "label": "", "display": "auto", "autoplay": False}
                ],
            }
        )
        self.assertEqual([field.field for field in merged_defaults.solution_fields], ["Definition"])

    def test_note_types_accept_text_lists(self) -> None:
        config = normalize_config({"note_types": "Basic, Cloze\nLanguage"})

        self.assertEqual(config.note_types, ["Basic", "Cloze", "Language"])

    def test_load_config_applies_matching_deck_profile(self) -> None:
        mw = FakeMw(
            {
                "language": "en",
                "target_field": "Front",
                "deck_configs": [
                    {
                        "name": "German vocabulary",
                        "deck_name": "German",
                        "language": "de",
                        "target_field": "German",
                        "database_path": "user_files/german_sentences.db",
                        "solution_fields": [{"field": "English", "display": "text"}],
                    }
                ],
            }
        )

        config = load_config(mw, "addon", deck_name="German")

        self.assertEqual(config.profile_name, "German vocabulary")
        self.assertEqual(config.active_deck_name, "German")
        self.assertEqual(config.language, "de")
        self.assertEqual(config.target_field, "German")
        self.assertEqual(config.database_path, "user_files/german_sentences.db")
        self.assertEqual([field.field for field in config.solution_fields], ["English"])

    def test_deck_profile_matches_subdecks_by_default(self) -> None:
        mw = FakeMw(
            {
                "language": "en",
                "deck_configs": [
                    {"name": "Spanish", "deck_name": "Spanish", "language": "es"}
                ],
            }
        )

        config = load_config(mw, "addon", deck_name="Spanish::Verbs")

        self.assertEqual(config.profile_name, "Spanish")
        self.assertEqual(config.language, "es")

    def test_more_specific_deck_profile_wins_over_parent_profile(self) -> None:
        mw = FakeMw(
            {
                "language": "en",
                "deck_configs": [
                    {"name": "Spanish", "deck_name": "Spanish", "language": "es"},
                    {
                        "name": "Spanish verbs",
                        "deck_name": "Spanish::Verbs",
                        "language": "es",
                        "target_field": "Verb",
                    },
                ],
            }
        )

        config = load_config(mw, "addon", deck_name="Spanish::Verbs")

        self.assertEqual(config.profile_name, "Spanish verbs")
        self.assertEqual(config.target_field, "Verb")

    def test_deck_profile_falls_back_to_global_config_when_no_match(self) -> None:
        mw = FakeMw(
            {
                "language": "en",
                "target_field": "Front",
                "deck_configs": [
                    {"name": "German", "deck_name": "German", "language": "de"}
                ],
            }
        )

        config = load_config(mw, "addon", deck_name="French")

        self.assertEqual(config.profile_name, "")
        self.assertEqual(config.language, "en")
        self.assertEqual(config.target_field, "Front")

    def test_deck_profile_language_uses_profile_dictionary_default(self) -> None:
        mw = FakeMw(
            {
                "language": "en",
                "dictionary_url_template": "https://en.wiktionary.org/wiki/{word}",
                "deck_configs": [
                    {"name": "Japanese", "deck_name": "Japanese", "language": "ja"}
                ],
            }
        )

        config = load_config(mw, "addon", deck_name="Japanese")

        self.assertEqual(config.language, "ja")
        self.assertEqual(config.dictionary_url_template, "https://jisho.org/search/{word}")

    def test_upsert_deck_config_preserves_other_profiles(self) -> None:
        raw = {
            "deck_configs": [
                {"name": "Spanish", "deck_name": "Spanish", "language": "es"},
                {"name": "German", "deck_name": "German", "language": "de"},
            ]
        }

        updated = upsert_deck_config(
            raw,
            "German",
            {"name": "German updated", "language": "de", "target_field": "Wort"},
        )
        config = load_config(FakeMw(updated), "addon", deck_name="German")
        self.assertEqual(config.profile_name, "German updated")
        self.assertEqual(config.target_field, "Wort")

    def test_upsert_deck_config_does_not_replace_parent_subdeck_match(self) -> None:
        raw = {
            "deck_configs": [
                {"name": "Spanish", "deck_name": "Spanish", "language": "es"}
            ]
        }

        updated = upsert_deck_config(
            raw,
            "Spanish::Verbs",
            {"name": "Spanish verbs", "language": "es", "target_field": "Verb"},
        )

        self.assertEqual(
            [(profile["name"], profile["deck_name"]) for profile in updated["deck_configs"]],
            [("Spanish", "Spanish"), ("Spanish verbs", "Spanish::Verbs")],
        )
        config = load_config(FakeMw(updated), "addon", deck_name="Spanish::Verbs")
        self.assertEqual(config.profile_name, "Spanish verbs")

    def test_invalid_scalar_config_values_fall_back_safely(self) -> None:
        config = normalize_config(
            {
                "deck_scope": "somewhere",
                "target_field": "  ",
                "include_new_cards": "not-a-boolean",
                "note_types": [None, "Basic", ""],
            }
        )

        self.assertEqual(config.deck_scope, "current")
        self.assertEqual(config.target_field, "Front")
        self.assertFalse(config.include_new_cards)
        self.assertEqual(config.note_types, ["Basic"])

    def test_default_database_path_uses_preserved_user_files(self) -> None:
        config = normalize_config({})

        self.assertEqual(config.database_path, DEFAULT_DATABASE_PATH)

    def test_legacy_default_database_path_is_migrated_in_config(self) -> None:
        config = normalize_config({"database_path": "data/contextual_sentences.db"})

        self.assertEqual(config.database_path, DEFAULT_DATABASE_PATH)

    def test_relative_database_path_cannot_escape_addon_folder(self) -> None:
        config = normalize_config({"database_path": "../outside.db"})

        with self.assertRaisesRegex(ValueError, "Relative database paths"):
            resolve_database_path(config)

    def test_relative_database_path_uses_configured_user_root(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            original = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                config = normalize_config({})
                resolved = resolve_database_path(config)
            finally:
                if original is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = original

        self.assertEqual(resolved, Path(tempdir).resolve() / DEFAULT_DATABASE_PATH)

    def test_load_config_copies_legacy_default_database_to_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            legacy = root / "data" / "contextual_sentences.db"
            target = root / "user_files" / "contextual_sentences.db"
            legacy.parent.mkdir()
            legacy.write_bytes(b"legacy db")
            mw = FakeMw({"database_path": "data/contextual_sentences.db"})
            original_addon_root = config_module.addon_root
            try:
                config_module.addon_root = lambda: root
                config = load_config(mw, "addon")
            finally:
                config_module.addon_root = original_addon_root

            self.assertEqual(config.database_path, DEFAULT_DATABASE_PATH)
            self.assertEqual(target.read_bytes(), b"legacy db")
            self.assertEqual(mw.addonManager.written, ("addon", {"database_path": DEFAULT_DATABASE_PATH}))


if __name__ == "__main__":
    unittest.main()
