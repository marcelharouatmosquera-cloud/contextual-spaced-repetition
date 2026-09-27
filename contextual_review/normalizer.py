"""Runtime-light tokenization and normalization shared by review and preprocessing."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from threading import local
from typing import Iterable, List

from .language_profiles import normalize_language_code, profile_ignored_words

COMBINING_MARKS = "\u0300-\u036f\u0610-\u061a\u064b-\u065f\u0670\u06d6-\u06ed"
LETTER_WITH_MARKS = r"[^\W\d_][%s]*" % COMBINING_MARKS
WORD_RE = re.compile(
    r"((?:%s)+(?:['\u2019\-](?:%s)+)*)"
    % (LETTER_WITH_MARKS, LETTER_WITH_MARKS),
    re.UNICODE,
)

EN_IRREGULARS = {
    "ate": "eat",
    "better": "good",
    "best": "good",
    "bought": "buy",
    "children": "child",
    "forgot": "forget",
    "forgotten": "forget",
    "gone": "go",
    "improved": "improve",
    "mice": "mouse",
    "ran": "run",
    "saw": "see",
    "seen": "see",
    "studies": "study",
    "went": "go",
    "wrote": "write",
    "written": "write",
}

UNSEGMENTED_LANGUAGE_CODES = {"ja", "ko", "zh"}
# Keep the established English/German rules and their imported mappings.
# Other profiled alphabetic languages use the bundled Snowball algorithms.
SNOWBALL_LANGUAGES = {
    "ar": "arabic", "da": "danish", "el": "greek", "es": "spanish",
    "fi": "finnish", "fr": "french", "it": "italian", "nl": "dutch",
    "pt": "portuguese", "ru": "russian", "sv": "swedish", "tr": "turkish",
}
_STEMMERS = local()


@dataclass(frozen=True)
class WordToken:
    text: str
    lemma: str
    is_word: bool = True


def tokenize_words(text: str, language: str = "en") -> List[WordToken]:
    return [
        WordToken(match.group(0), normalize_word(match.group(0), language), True)
        for match in WORD_RE.finditer(text)
    ]


def split_text_tokens(text: str, language: str = "en") -> List[WordToken]:
    parts: List[WordToken] = []
    pos = 0
    for match in WORD_RE.finditer(text):
        if match.start() > pos:
            parts.append(WordToken(text[pos : match.start()], "", False))
        word = match.group(0)
        parts.append(WordToken(word, normalize_word(word, language), True))
        pos = match.end()
    if pos < len(text):
        parts.append(WordToken(text[pos:], "", False))
    return parts


def normalize_word(word: str, language: str = "en") -> str:
    text = normalize_form(word)
    if not text:
        return ""

    lang = normalize_language_code(language)
    if lang == "en":
        return _stem_english(text)
    if lang == "de":
        return _stem_german(text)
    if lang in SNOWBALL_LANGUAGES:
        return _snowball_stem(stemmer_form(word, lang), lang)
    return text


def uses_stem_expansion(language: str) -> bool:
    """Whether word families are found by stemming corpus forms at query time.

    Corpora imported before a language gained a stemmer store each form as its
    own base, so these languages cannot rely on the stored ``word_forms`` bases.
    """
    return normalize_language_code(language) in SNOWBALL_LANGUAGES


def lookup_form(word: str, language: str = "en") -> str:
    """Return a word for dictionaries, translation, and mining.

    Unlike ``normalize_form`` this keeps diacritics, so Russian й/ё and German
    umlauts survive. German keeps its case because noun capitals are lexical.
    """
    text = unicodedata.normalize("NFC", str(word).replace("’", "'")).strip()
    if normalize_language_code(language) == "de":
        return text
    return text.lower()


def matching_key_for_word(word: str, language: str = "en", matching_mode: str = "exact_form") -> str:
    if matching_mode == "exact_form":
        return normalize_form(word)
    return normalize_word(word, language)


def normalize_form(word: str) -> str:
    text = _ascii_fold(str(word).casefold().replace("\u2019", "'"))
    return _strip_non_letters(text)


def select_target_tokens(
    text: str,
    language: str = "en",
    mode: str = "content_words",
    ignored_words: Iterable[str] = (),
) -> List[WordToken]:
    tokens = tokenize_words(text, language)
    if mode == "all_words":
        return tokens
    if mode == "first_word":
        return tokens[:1]

    ignored = _ignored_word_set(ignored_words, language)
    content = [token for token in tokens if not is_function_word(token.text, language, ignored)]
    return content or tokens[:1]


def is_function_word(word: str, language: str = "en", ignored_words: Iterable[str] = ()) -> bool:
    lang = normalize_language_code(language)
    form = normalize_form(word)
    lemma = normalize_word(word, lang)
    blocked = set(_ignored_word_set(profile_ignored_words(lang), lang))
    blocked.update(_ignored_word_set(ignored_words, lang))
    return form in blocked or lemma in blocked


def _ignored_word_set(words: Iterable[str], language: str) -> set[str]:
    ignored = set()
    for word in words:
        form = normalize_form(word)
        lemma = normalize_word(word, language)
        if form:
            ignored.add(form)
        if lemma:
            ignored.add(lemma)
    return ignored


def count_words(text: str, language: str = "") -> int:
    if is_unsegmented_language(language) or contains_unsegmented_script(text):
        script_chars = sum(1 for char in str(text or "") if _is_cjk_or_kana(char))
        non_script_text = "".join(" " if _is_cjk_or_kana(char) else char for char in str(text or ""))
        spaced_words = len(WORD_RE.findall(non_script_text))
        approximate_script_words = (script_chars + 2) // 3
        return spaced_words + approximate_script_words
    return len(WORD_RE.findall(text))


def is_unsegmented_language(language: str) -> bool:
    return normalize_language_code(language) in UNSEGMENTED_LANGUAGE_CODES


def contains_unsegmented_script(text: str) -> bool:
    return any(_is_cjk_or_kana(char) for char in str(text or ""))


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(
        char
        for char in decomposed
        if not unicodedata.combining(char) or char in {"\u3099", "\u309a"}
    )
    return unicodedata.normalize("NFC", folded)


def _strip_non_letters(text: str) -> str:
    return "".join(char for char in text if char.isalpha())


def _is_cjk_or_kana(char: str) -> bool:
    code = ord(char)
    return (
        0x3040 <= code <= 0x30FF
        or 0x3400 <= code <= 0x4DBF
        or 0x4E00 <= code <= 0x9FFF
        or 0x1100 <= code <= 0x11FF
        or 0x3130 <= code <= 0x318F
        or 0xAC00 <= code <= 0xD7AF
        or 0xF900 <= code <= 0xFAFF
    )


def _stem_english(text: str) -> str:
    if text in EN_IRREGULARS:
        return EN_IRREGULARS[text]
    if len(text) <= 3:
        return text
    if text.endswith("'s"):
        text = text[:-2]
    if len(text) > 4 and text.endswith("ies"):
        return text[:-3] + "y"
    if len(text) > 5 and text.endswith("ing"):
        stem = text[:-3]
        return _undouble_final(stem)
    if len(text) > 4 and text.endswith("ed"):
        stem = text[:-2]
        return _undouble_final(stem)
    if len(text) > 4 and text.endswith("es"):
        return text[:-2]
    if len(text) > 3 and text.endswith("s") and not text.endswith("ss"):
        return text[:-1]
    return text


def _stem_german(text: str) -> str:
    if len(text) <= 4:
        return text
    for suffix in ("ern", "em", "er", "en", "es", "e", "n", "s"):
        if len(text) - len(suffix) >= 4 and text.endswith(suffix):
            return text[: -len(suffix)]
    return text


def stemmer_form(word: str, language: str) -> str:
    """Keep linguistic letters until after stemming (й, ñ, accents, dotless ı)."""
    text = unicodedata.normalize("NFC", str(word))
    if language == "tr":
        text = text.replace("I", "ı").replace("İ", "i")
    if language == "ru":
        text = text.replace("\u0301", "")  # optional dictionary stress
    return _strip_non_letters(text.lower())


@lru_cache(maxsize=65536)
def _snowball_stem(text: str, language: str) -> str:
    # Generated stemmers mutate their working buffer. Never share an instance
    # between Anki's GUI thread and the background sentence/import workers.
    if not hasattr(_STEMMERS, "by_language"):
        _STEMMERS.by_language = {}
    stemmer = _STEMMERS.by_language.get(language)
    if stemmer is None:
        algorithm = SNOWBALL_LANGUAGES[language]
        module = import_module("._vendor.snowballstemmer.%s_stemmer" % algorithm, __package__)
        # Use the bundled pure-Python class even if another add-on installed
        # the optional native Stemmer module or a different Snowball version.
        stemmer = getattr(module, algorithm.title() + "Stemmer")()
        _STEMMERS.by_language[language] = stemmer
    return normalize_form(stemmer.stemWord(text))


def _undouble_final(text: str) -> str:
    if len(text) > 2 and text[-1] == text[-2] and text[-1] in "bcdfghjklmnpqrstvwxyz":
        return text[:-1]
    return text
