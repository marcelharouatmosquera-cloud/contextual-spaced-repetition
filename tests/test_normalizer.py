from __future__ import annotations

import unittest

from contextual_review.normalizer import (
    count_words,
    matching_key_for_word,
    normalize_form,
    normalize_word,
    select_target_tokens,
    split_text_tokens,
)


class NormalizerTests(unittest.TestCase):
    def test_normalize_english_common_forms(self) -> None:
        self.assertEqual(normalize_word("Forgotten", "en"), "forget")
        self.assertEqual(normalize_word("studies", "en"), "study")
        self.assertEqual(normalize_word("reviewed", "en"), "review")
        self.assertEqual(normalize_word("cards", "en"), "card")
        self.assertEqual(normalize_word("improved", "en"), "improve")

    def test_normalize_non_english_letters(self) -> None:
        self.assertEqual(normalize_word("ma\u00f1ana", "es"), "manana")

    def test_normalize_form_keeps_inflected_surface(self) -> None:
        self.assertEqual(normalize_form("Students,"), "students")
        self.assertEqual(normalize_form("mother-in-law"), "motherinlaw")
        self.assertEqual(normalize_form("can't"), "cant")
        self.assertEqual(normalize_word("Students,", "en"), "student")

    def test_split_text_tokens_preserves_punctuation(self) -> None:
        tokens = split_text_tokens("Review, then remember.", "en")
        self.assertEqual([token.text for token in tokens], ["Review", ", ", "then", " ", "remember", "."])
        self.assertFalse(tokens[1].is_word)

    def test_count_words(self) -> None:
        self.assertEqual(count_words("One short sentence."), 3)

    def test_japanese_normalization_preserves_voicing_and_estimates_sentence_units(self) -> None:
        word = "\u98df\u3079\u308b"
        sentence = "\u732b\u304c\u9b5a\u3092\u98df\u3079\u308b\u3002"

        self.assertEqual(normalize_form(word), word)
        self.assertEqual(count_words(sentence, "ja"), 3)

    def test_content_word_extraction_skips_german_articles(self) -> None:
        tokens = select_target_tokens("der Hund", "de", "content_words")
        self.assertEqual([token.text for token in tokens], ["Hund"])

    def test_content_word_extraction_skips_russian_function_words(self) -> None:
        tokens = select_target_tokens("\u0432 \u0434\u043e\u043c\u0435", "ru", "content_words")
        self.assertEqual([token.text for token in tokens], ["\u0434\u043e\u043c\u0435"])

    def test_russian_combining_stress_marks_stay_in_same_word(self) -> None:
        tokens = select_target_tokens("\u043f\u043e\u0301\u0432\u043e\u0434", "ru", "content_words")

        self.assertEqual([token.text for token in tokens], ["\u043f\u043e\u0301\u0432\u043e\u0434"])
        self.assertEqual([token.lemma for token in tokens], ["\u043f\u043e\u0432\u043e\u0434"])

    def test_matching_key_can_use_exact_surface_form(self) -> None:
        self.assertEqual(matching_key_for_word("Hunde", "de", "exact_form"), "hunde")
        self.assertEqual(matching_key_for_word("Hunde", "de", "lemma_family"), "hund")

    def test_content_word_extraction_accepts_custom_ignored_words(self) -> None:
        tokens = select_target_tokens("xx casa", "es", "content_words", ["xx"])
        self.assertEqual([token.text for token in tokens], ["casa"])

    def test_content_word_extraction_uses_language_profile_words(self) -> None:
        tokens = select_target_tokens("el gato", "es", "content_words")
        self.assertEqual([token.text for token in tokens], ["gato"])


if __name__ == "__main__":
    unittest.main()
