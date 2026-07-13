from __future__ import annotations

import unittest

from contextual_review import translation


class TranslationTests(unittest.TestCase):
    def tearDown(self) -> None:
        translation.translate_text.cache_clear()

    def test_google_translation_normalizes_languages_and_caches_results(self) -> None:
        calls = []

        class FakeGoogleTranslator:
            def __init__(self, source: str, target: str) -> None:
                calls.append(("init", source, target))

            def translate(self, text: str) -> str:
                calls.append(("translate", text))
                return "House"

        original = translation._load_google_translator
        try:
            translation._load_google_translator = lambda: FakeGoogleTranslator
            first = translation.translate_text("Haus", "deu", "eng")
            second = translation.translate_text("Haus", "deu", "eng")
        finally:
            translation._load_google_translator = original

        self.assertEqual((first, second), ("House", "House"))
        self.assertEqual(
            calls,
            [("init", "de", "en"), ("translate", "Haus")],
        )


if __name__ == "__main__":
    unittest.main()
