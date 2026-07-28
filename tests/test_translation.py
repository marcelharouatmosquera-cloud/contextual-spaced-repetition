from __future__ import annotations

import unittest
import sys
from types import ModuleType

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

    def test_google_module_requests_are_given_a_bounded_timeout(self) -> None:
        calls = []

        class FakeRequests:
            def get(self, *args, **kwargs):
                calls.append((args, kwargs))
                return object()

        module_name = "tests.fake_deep_translator_google"
        module = ModuleType(module_name)
        module.requests = FakeRequests()
        sys.modules[module_name] = module

        class FakeGoogleTranslator:
            pass

        FakeGoogleTranslator.__module__ = module_name
        try:
            translation._configure_google_timeout(FakeGoogleTranslator)
            module.requests.get("https://example.test")
        finally:
            sys.modules.pop(module_name, None)

        self.assertEqual(calls[0][1]["timeout"], (4, 8))


if __name__ == "__main__":
    unittest.main()
