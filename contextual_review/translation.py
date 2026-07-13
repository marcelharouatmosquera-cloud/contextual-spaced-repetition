"""Small cached wrapper around the bundled deep-translator Google client."""

from __future__ import annotations

import sys
from functools import lru_cache
from pathlib import Path

from .language_profiles import normalize_language_code


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

    GoogleTranslator = _load_google_translator()
    translated = GoogleTranslator(source=source, target=target).translate(value)
    result = str(translated or "").strip()
    if not result:
        raise RuntimeError("Google returned an empty translation.")
    return result


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
