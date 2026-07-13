from __future__ import annotations

import unittest

from contextual_review.config import normalize_config
from contextual_review.importer import tatoeba_code
from contextual_review.language_profiles import (
    get_language_profile,
    normalize_language_code,
    profile_dictionary_url,
)


class LanguageProfileTests(unittest.TestCase):
    def test_profile_provides_tatoeba_code(self) -> None:
        self.assertEqual(tatoeba_code("es"), "spa")
        self.assertEqual(tatoeba_code("ru"), "rus")
        self.assertEqual(tatoeba_code("rus"), "rus")

    def test_tatoeba_code_alias_normalizes_for_settings(self) -> None:
        config = normalize_config({"language": "rus"})

        self.assertEqual(config.language, "ru")

    def test_profile_provides_dictionary_default(self) -> None:
        config = normalize_config({"language": "fr", "dictionary_url_template": ""})

        self.assertEqual(config.dictionary_url_template, profile_dictionary_url("fr"))
        self.assertIn("{word}", config.dictionary_url_template)

    def test_unknown_language_has_safe_defaults(self) -> None:
        profile = get_language_profile("zz")

        self.assertEqual(profile.code, "zz")
        self.assertEqual(profile.ignored_target_words, [])
        self.assertEqual(tatoeba_code("zz"), "zz")

    def test_locale_style_language_codes_use_their_base_language(self) -> None:
        self.assertEqual(normalize_language_code("de_DE"), "de")
        self.assertEqual(normalize_language_code("es-MX"), "es")
        self.assertEqual(tatoeba_code("pt_BR"), "por")


if __name__ == "__main__":
    unittest.main()
