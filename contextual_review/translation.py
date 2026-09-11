"""Small cached wrapper around the bundled deep-translator Google client."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

from .language_profiles import normalize_language_code


TRANSLATION_CONNECT_TIMEOUT_SECONDS = 4
TRANSLATION_READ_TIMEOUT_SECONDS = 8
TRANSLATION_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


class _RequestsTimeoutProxy:
    """Give deep-translator's module-local requests binding a safe timeout."""

    _contextual_review_timeout_proxy = True

    def __init__(self, requests_module: Any) -> None:
        self._requests_module = requests_module

    def get(self, *args: Any, **kwargs: Any) -> Any:
        headers = dict(kwargs.get("headers") or {})
        if not any(str(name).casefold() == "user-agent" for name in headers):
            # Google currently serves an embedded Error 500 page to the
            # default python-requests identity used by deep-translator 1.11.4.
            headers["User-Agent"] = TRANSLATION_USER_AGENT
        kwargs["headers"] = headers
        kwargs.setdefault(
            "timeout",
            (TRANSLATION_CONNECT_TIMEOUT_SECONDS, TRANSLATION_READ_TIMEOUT_SECONDS),
        )
        return self._requests_module.get(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._requests_module, name)


@lru_cache(maxsize=512)
def translate_text(text: str, source_language: str, target_language: str) -> str:
    """Translate text with Google through deep-translator and cache the result."""
    value = str(text or "").strip()
    if not value:
        raise ValueError("There is no text to translate.")

    source = normalize_language_code(source_language) or "auto"
    target = normalize_language_code(target_language) or "en"
    if source == target:
        return value

    GoogleTranslator = _configure_google_timeout(_load_google_translator())
    translated = GoogleTranslator(source=source, target=target).translate(value)
    result = str(translated or "").strip()
    if not result:
        raise RuntimeError("Google returned an empty translation.")
    return result


def _configure_google_timeout(translator_class: Any) -> Any:
    """Patch only deep-translator's Google module, not global requests."""
    module = sys.modules.get(str(getattr(translator_class, "__module__", "") or ""))
    requests_binding = getattr(module, "requests", None) if module is not None else None
    if requests_binding is not None and not bool(
        getattr(requests_binding, "_contextual_review_timeout_proxy", False)
    ):
        module.requests = _RequestsTimeoutProxy(requests_binding)
    return translator_class


def _load_google_translator():
    try:
        from deep_translator import GoogleTranslator

        return GoogleTranslator
    except ImportError:
        vendor_path = Path(__file__).resolve().parent / "_vendor"
        if str(vendor_path) not in sys.path:
            # Prefer Anki's libraries, while keeping the packaged dependency
            # available when deep-translator is not installed globally.
            sys.path.append(str(vendor_path))
        try:
            from deep_translator import GoogleTranslator

            return GoogleTranslator
        except ImportError as exc:
            raise RuntimeError(
                "The bundled deep-translator component could not be loaded."
            ) from exc
