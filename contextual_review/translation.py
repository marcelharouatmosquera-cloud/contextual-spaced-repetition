"""Cached Google translation with an independent fallback during rate limits."""

from __future__ import annotations

import sys
from functools import lru_cache
from html import unescape
from pathlib import Path
from time import monotonic
from typing import Any

from .language_profiles import normalize_language_code


TRANSLATION_CONNECT_TIMEOUT_SECONDS = 4
TRANSLATION_READ_TIMEOUT_SECONDS = 8
TRANSLATION_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)
MYMEMORY_TRANSLATE_URL = "https://api.mymemory.translated.net/get"
GOOGLE_HTML_RATE_LIMIT_COOLDOWN_SECONDS = 300


_google_html_rate_limited_until = 0.0


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
    """Translate text, falling back during Google rate limits; cache successes."""
    value = str(text or "").strip()
    if not value:
        raise ValueError("There is no text to translate.")

    source = normalize_language_code(source_language) or "auto"
    target = normalize_language_code(target_language) or "en"
    if source == target:
        return value

    if monotonic() < _google_html_rate_limited_until:
        translated = _translate_with_mymemory(value, source, target)
    else:
        GoogleTranslator = _configure_google_timeout(_load_google_translator())
        try:
            translated = GoogleTranslator(source=source, target=target).translate(value)
        except Exception as exc:
            if not _is_rate_limit_error(exc):
                raise
            _remember_google_html_rate_limit()
            translated = _translate_with_mymemory(value, source, target)
    result = str(translated or "").strip()
    if not result:
        raise RuntimeError("The translation service returned an empty translation.")
    return result


def _remember_google_html_rate_limit() -> None:
    global _google_html_rate_limited_until
    _google_html_rate_limited_until = (
        monotonic() + GOOGLE_HTML_RATE_LIMIT_COOLDOWN_SECONDS
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    detail = f"{type(exc).__name__}: {exc}".casefold()
    return any(
        marker in detail
        for marker in ("toomanyrequests", "too many requests", "rate limit", "429")
    )


def _translate_with_mymemory(text: str, source: str, target: str) -> str:
    """Use an independent provider when Google's HTML endpoint is rate-limited."""
    if source == "auto":
        raise RuntimeError("The fallback service requires a known source language.")
    if len(text.encode("utf-8")) > 500:
        raise RuntimeError("The text exceeds the fallback service's 500-byte limit.")
    requests = _load_requests()
    response = requests.get(
        MYMEMORY_TRANSLATE_URL,
        params={
            "q": text,
            "langpair": f"{source}|{target}",
        },
        headers={"User-Agent": TRANSLATION_USER_AGENT},
        timeout=(TRANSLATION_CONNECT_TIMEOUT_SECONDS, TRANSLATION_READ_TIMEOUT_SECONDS),
    )
    try:
        response.raise_for_status()
        payload = response.json()
    finally:
        response.close()

    if not isinstance(payload, dict):
        raise RuntimeError("The fallback service returned an invalid response.")
    status = str(payload.get("responseStatus", ""))
    if status != "200" or payload.get("quotaFinished"):
        detail = str(payload.get("responseDetails") or "").strip()
        if status == "429" or payload.get("quotaFinished"):
            raise RuntimeError("The fallback translation service rate limit was reached.")
        raise RuntimeError(detail or "The fallback service rejected the translation.")
    try:
        response_data = payload.get("responseData")
        translated = response_data.get("translatedText")
        if not isinstance(translated, str):
            raise TypeError("Translation must be text")
        translated = unescape(translated).strip()
    except (AttributeError, TypeError) as exc:
        raise RuntimeError("The fallback service returned an invalid response.") from exc
    if not translated:
        detail = str(payload.get("responseDetails") or "").strip()
        raise RuntimeError(detail or "The fallback service returned no translation.")
    return translated


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


def _load_requests():
    try:
        import requests

        return requests
    except ImportError:
        vendor_path = Path(__file__).resolve().parent / "_vendor"
        if str(vendor_path) not in sys.path:
            sys.path.append(str(vendor_path))
        try:
            import requests

            return requests
        except ImportError as exc:
            raise RuntimeError("The bundled HTTP component could not be loaded.") from exc
