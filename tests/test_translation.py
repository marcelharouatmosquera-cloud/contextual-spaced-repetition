from __future__ import annotations

import unittest
import sys
from types import ModuleType
from unittest.mock import Mock, patch

from contextual_review import translation


class TranslationTests(unittest.TestCase):
    def tearDown(self) -> None:
        translation.translate_text.cache_clear()
        translation._google_html_rate_limited_until = 0.0

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

    def test_google_module_requests_are_given_browser_identity_and_timeout(self) -> None:
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
        self.assertEqual(
            calls[0][1]["headers"]["User-Agent"],
            translation.TRANSLATION_USER_AGENT,
        )

    def test_google_request_preserves_an_explicit_user_agent(self) -> None:
        calls = []

        class FakeRequests:
            def get(self, *args, **kwargs):
                calls.append((args, kwargs))
                return object()

        proxy = translation._RequestsTimeoutProxy(FakeRequests())
        proxy.get(
            "https://example.test",
            headers={"user-agent": "Contextual Review test client"},
        )

        self.assertEqual(
            calls[0][1]["headers"],
            {"user-agent": "Contextual Review test client"},
        )

    def test_google_rate_limit_falls_back_to_independent_provider(self) -> None:
        calls = []

        class TooManyRequests(Exception):
            pass

        class FakeGoogleTranslator:
            def __init__(self, source: str, target: str) -> None:
                calls.append(("html_init", source, target))

            def translate(self, text: str) -> str:
                raise TooManyRequests("429: too many requests")

        class FakeResponse:
            def raise_for_status(self) -> None:
                pass

            def json(self):
                return {
                    "responseStatus": 200,
                    "responseData": {
                        "translatedText": "What skills should a leader have?"
                    }
                }

            def close(self) -> None:
                calls.append(("close",))

        class FakeRequests:
            def get(self, url: str, **kwargs):
                calls.append(("fallback_get", url, kwargs))
                return FakeResponse()

        original_translator = translation._load_google_translator
        original_requests = translation._load_requests
        try:
            translation._load_google_translator = lambda: FakeGoogleTranslator
            translation._load_requests = lambda: FakeRequests()
            result = translation.translate_text(
                "Какими навыками должен обладать лидер?", "rus", "eng"
            )
        finally:
            translation._load_google_translator = original_translator
            translation._load_requests = original_requests

        self.assertEqual(result, "What skills should a leader have?")
        self.assertEqual(calls[0], ("html_init", "ru", "en"))
        self.assertEqual(
            calls[1][0:2],
            ("fallback_get", translation.MYMEMORY_TRANSLATE_URL),
        )
        self.assertEqual(calls[1][2]["params"]["langpair"], "ru|en")
        self.assertEqual(calls[1][2]["timeout"], (4, 8))
        self.assertGreater(translation._google_html_rate_limited_until, 0.0)
        self.assertEqual(calls[-1], ("close",))

    def test_recent_rate_limit_bypasses_html_translator(self) -> None:
        calls = []

        class FakeResponse:
            def raise_for_status(self) -> None:
                pass

            def json(self):
                return {"responseStatus": 200, "responseData": {"translatedText": "fresh"}}

            def close(self) -> None:
                pass

        class FakeRequests:
            def get(self, *args, **kwargs):
                calls.append((args, kwargs))
                return FakeResponse()

        original_translator = translation._load_google_translator
        original_requests = translation._load_requests
        try:
            translation._google_html_rate_limited_until = float("inf")
            translation._load_google_translator = lambda: self.fail(
                "The known rate-limited HTML provider should be bypassed."
            )
            translation._load_requests = lambda: FakeRequests()
            result = translation.translate_text("свежий", "ru", "en")
        finally:
            translation._load_google_translator = original_translator
            translation._load_requests = original_requests

        self.assertEqual(result, "fresh")
        self.assertEqual(len(calls), 1)


    def test_fallback_errors_are_never_cached_as_translations(self) -> None:
        for payload in (
            {"responseStatus": 429, "responseData": {"translatedText": "QUOTA EXCEEDED"}},
            {"responseStatus": 403, "responseData": {"translatedText": "INVALID LANGUAGE"}},
            {"responseStatus": 200, "quotaFinished": True,
             "responseData": {"translatedText": "QUOTA EXCEEDED"}},
            {"responseStatus": 200, "responseData": {"translatedText": ["bad"]}},
            {"responseStatus": 200, "responseData": {"translatedText": ""}},
            [],
        ):
            with self.subTest(payload=payload):
                response = Mock()
                response.json.return_value = payload
                requests = Mock()
                requests.get.return_value = response
                translation._google_html_rate_limited_until = float("inf")
                with patch.object(translation, "_load_requests", return_value=requests):
                    with self.assertRaises(RuntimeError):
                        translation.translate_text("слово", "ru", "en")
                    response.json.return_value = {
                        "responseStatus": "200",
                        "responseData": {"translatedText": "word &amp; meaning"},
                    }
                    self.assertEqual(translation.translate_text("слово", "ru", "en"),
                                     "word & meaning")
                self.assertEqual(requests.get.call_count, 2)
                self.assertEqual(response.close.call_count, 2)
                translation.translate_text.cache_clear()

    def test_google_is_retried_after_cooldown(self) -> None:
        translation._google_html_rate_limited_until = 10
        translator = Mock()
        translator.return_value.translate.return_value = "word"
        with patch.object(translation, "monotonic", return_value=11), \
                patch.object(translation, "_load_google_translator", return_value=translator):
            self.assertEqual(translation.translate_text("слово", "ru", "en"), "word")
        translator.return_value.translate.assert_called_once_with("слово")


if __name__ == "__main__":
    unittest.main()
