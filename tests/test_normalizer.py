from __future__ import annotations

import unittest

from contextual_review.normalizer import (
    count_words,
    lookup_form,
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

    def test_russian_stemmer_matches_snowball_reference_stems(self) -> None:
        # Stems given by the Snowball Russian algorithm, written after this
        # add-on's й -> и and ё -> е folding.
        expected = {
            "вагонами": "вагон",
            "важнейшие": "важн",
            "вбежала": "вбежа",
            "ввалился": "ввал",
            "вашего": "ваш",
            "сделавшись": "сдела",
            "действительность": "деиствительн",
            "длинный": "длин",
        }
        for word, stem in expected.items():
            with self.subTest(word=word):
                self.assertEqual(normalize_word(word, "ru"), stem)

    def test_russian_lemma_family_joins_inflected_forms(self) -> None:
        families = [
            ["поездка", "поездку", "поездки", "поездке", "поездкой", "поездках"],
            ["стол", "стола", "столу", "столом", "столе", "столов", "столами"],
            ["красивый", "красивая", "красивое", "красивого", "красивыми"],
            ["говорить", "говорю", "говорит", "говорите", "говорят", "говорили"],
        ]
        for family in families:
            with self.subTest(word=family[0]):
                self.assertEqual(
                    {matching_key_for_word(word, "ru", "lemma_family") for word in family},
                    {matching_key_for_word(family[0], "ru", "lemma_family")},
                )
        self.assertNotEqual(normalize_word("столица", "ru"), normalize_word("стол", "ru"))
        self.assertEqual(matching_key_for_word("поездку", "ru", "exact_form"), "поездку")

    def test_russian_stemmer_leaves_short_and_latin_words_intact(self) -> None:
        self.assertEqual(normalize_word("он", "ru"), "он")
        self.assertEqual(normalize_word("что", "ru"), "что")
        self.assertEqual(normalize_word("Anki", "ru"), "anki")

    def test_lookup_form_keeps_diacritics_for_dictionaries_and_mining(self) -> None:
        self.assertEqual(lookup_form("Действительность", "ru"), "действительность")
        self.assertEqual(lookup_form("Мой", "ru"), "мой")
        self.assertEqual(lookup_form("ещё", "ru"), "ещё")
        self.assertEqual(lookup_form("Mädchen", "de"), "Mädchen")
        self.assertEqual(lookup_form("Café", "fr"), "café")


if __name__ == "__main__":
    unittest.main()
