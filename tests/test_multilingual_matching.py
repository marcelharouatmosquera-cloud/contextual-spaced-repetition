from __future__ import annotations

import hashlib
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from contextual_review.config import normalize_config
from contextual_review.corpus import initialize_database, insert_sentence, select_review_task, upsert_word_forms
from contextual_review.diagnostics import _matching_check
from contextual_review.normalizer import matching_key_for_word, normalize_form, normalize_word, tokenize_words
from contextual_review.types import DueCard
from contextual_review import word_families


# Independent linguistic examples include prefix removal, changed endings,
# accents and case. They must reach the selected task and its exact card IDs.
EXAMPLES = {
    "ar": ("كتاب", "أقرأ الكتاب اليوم", "الكتاب"),
    "da": ("bil", "Vi ser bilerne her", "bilerne"),
    "el": ("άνθρωπος", "Οι άνθρωποι είναι εδώ", "άνθρωποι"),
    "es": ("canción", "Escucho canciones nuevas", "canciones"),
    "fi": ("talo", "Asun talossa nyt", "talossa"),
    "fr": ("cheval", "Les chevaux arrivent ici", "chevaux"),
    "it": ("ragazzo", "I ragazzi sono qui", "ragazzi"),
    "nl": ("huis", "De huizen zijn groot", "huizen"),
    "pt": ("gato", "Os gatos estão aqui", "gatos"),
    "ru": ("поездка", "Мы говорим о поездке домой", "поездке"),
    "sv": ("bil", "Vi ser bilarna här", "bilarna"),
    "tr": ("ev", "Biz evlerde kalıyoruz", "evlerde"),
}


def due(word, language, card_id=1, mode="lemma_family"):
    return DueCard(card_id, word, normalize_word(word, language),
                   word_form=normalize_form(word), match_key=matching_key_for_word(word, language, mode))


class MultilingualMatchingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "sentences.db"
        initialize_database(self.path)

    def insert(self, language, text, mappings=None):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            # Mimic an existing library imported before stemming was supported.
            mappings = mappings or {normalize_form(t.text): normalize_form(t.text)
                                    for t in tokenize_words(text, language)}
            return insert_sentence(conn, language, text, None, mappings)

    def select(self, language, cards, mode="lemma_family"):
        return select_review_task(self.path, cards, language, set(), 50, matching_mode=mode)

    def test_every_added_language_selects_and_highlights_a_legacy_inflection(self):
        for language, (base, sentence, surface) in EXAMPLES.items():
            with self.subTest(language=language):
                self.insert(language, sentence)
                task = self.select(language, [due(base, language)])
                self.assertIsNotNone(task)
                targets = [token for token in task.tokens if token.is_target]
                self.assertEqual([(t.text, t.card_ids) for t in targets], [(surface, (1,))])
                self.assertEqual(targets[0].lookup_text, surface.lower())
                self.assertIsNone(self.select(language, [due(base, language, mode="exact_form")], "exact_form"))

    def test_multi_target_selection_and_recall_keep_both_cards(self):
        self.insert("fr", "Les chevaux regardent les chats")
        from dataclasses import replace
        cards = [replace(due(w, "fr", i), direction="recall", definition="hint")
                 for i, w in enumerate(("cheval", "chat"), 1)]
        task = self.select("fr", cards)
        self.assertEqual({cid for ids in task.card_ids_by_key.values() for cid in ids}, {1, 2})
        self.assertEqual([(t.text, t.direction) for t in task.tokens if t.is_target],
                         [("chevaux", "recall"), ("chats", "recall")])

    def test_imported_irregulars_still_work(self):
        self.insert("fr", "Je suis ici maintenant")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            upsert_word_forms(conn, {"suis": "etre"})
        task = self.select("fr", [due("être", "fr")])
        self.assertIsNotNone(task)
        self.assertEqual([t.text for t in task.tokens if t.is_target], ["suis"])

    def test_original_russian_letters_are_checked_before_grading(self):
        # The old folded stemmer reduced both to "бо".
        self.insert("ru", "Вы бойтесь этого человека")
        self.assertIsNone(self.select("ru", [due("бой", "ru")]))

    def test_turkish_uppercase_dotless_i_and_arabic_vowel_marks(self):
        self.assertEqual(normalize_word("KIZLAR", "tr"), normalize_word("kız", "tr"))
        self.insert("tr", "Bu KIZLAR burada")
        task = self.select("tr", [due("kız", "tr")])
        self.assertEqual([t.text for t in task.tokens if t.is_target], ["KIZLAR"])
        self.assertEqual(len(tokenize_words("الْكِتَاب", "ar")), 1)
        self.assertEqual(normalize_word("الْكِتَاب", "ar"), normalize_word("كتاب", "ar"))

    def test_language_aliases_and_read_only_index(self):
        self.insert("fra", "Les chevaux sont ici")
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        self.assertIsNotNone(self.select("fr-FR", [due("cheval", "fr-FR")]))
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_cached_families_refresh_after_import_and_deletion(self):
        first = self.insert("fr", "Les chevaux sont ici")
        with patch.object(word_families, "_build_index", wraps=word_families._build_index) as build:
            self.assertIsNotNone(self.select("fr", [due("cheval", "fr")]))
            self.assertIsNotNone(self.select("fr", [due("cheval", "fr")]))
            self.assertEqual(build.call_count, 1)
            self.insert("fr", "Les chats sont ici")
            self.assertIsNotNone(self.select("fr", [due("chat", "fr")]))
            self.assertEqual(build.call_count, 2)
            with closing(sqlite3.connect(self.path)) as conn, conn:
                conn.execute("DELETE FROM sentences WHERE id = ?", (first,))
            self.assertIsNone(self.select("fr", [due("cheval", "fr")]))
            self.assertEqual(build.call_count, 3)

    def test_cache_refreshes_for_wal_commits(self):
        writer = sqlite3.connect(self.path)
        self.addCleanup(writer.close)
        writer.execute("PRAGMA journal_mode=WAL")
        self.insert("fr", "Les chevaux sont ici")
        self.assertIsNone(self.select("fr", [due("chat", "fr")]))
        self.insert("fr", "Les chats sont ici")
        self.assertIsNotNone(self.select("fr", [due("chat", "fr")]))

    def test_stemmer_instances_are_safe_across_workers(self):
        examples = [(lang, word, normalize_word(word, lang))
                    for lang, (base, _, surface) in EXAMPLES.items() for word in (base, surface)]
        from contextual_review.normalizer import _snowball_stem
        _snowball_stem.cache_clear()
        with ThreadPoolExecutor(max_workers=8) as pool:
            actual = list(pool.map(lambda row: normalize_word(row[1], row[0]), examples * 50))
        self.assertEqual(actual, [row[2] for row in examples * 50])

    def test_diagnostics_explain_languages_without_stemmers(self):
        for language in ("pl", "uk"):
            check = _matching_check(normalize_config({"language": language, "matching_mode": "lemma_family"}))
            self.assertEqual(check.status, "warning")
            self.assertIn("import", check.detail)
        for language in EXAMPLES:
            check = _matching_check(normalize_config({"language": language, "matching_mode": "lemma_family"}))
            self.assertEqual(check.status, "ok")


if __name__ == "__main__":
    unittest.main()
