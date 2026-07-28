"""Conservative deck field and card-direction detection for beginner setup."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from .anki_bridge import card_question_format, card_template_name, note_field_names
from .language_profiles import get_language_profile, profile_ignored_words
from .template_fields import visible_question_field_names


MAX_INSPECTED_CARDS = 20000

ENGLISH_WORDS = {
    "a", "about", "after", "all", "also", "an", "and", "answer", "are", "as",
    "at", "back", "be", "because", "been", "before", "book", "but", "by", "can",
    "card", "cat", "come", "day", "definition", "do", "dog", "down", "each", "english",
    "example", "find", "first", "for", "from", "get", "give", "go", "good", "had",
    "has", "have", "he", "help", "her", "here", "him", "his", "house", "how", "i",
    "if", "in", "into", "is", "it", "know", "language", "learn", "like", "look",
    "make", "meaning", "more", "my", "new", "no", "not", "now", "of", "on", "one",
    "only", "or", "other", "our", "out", "people", "read", "review", "say", "see",
    "sentence", "she", "so", "some", "take", "text", "than", "that", "the", "their",
    "them", "then", "there", "these", "they", "thing", "this", "time", "to", "translation",
    "two", "up", "use", "very", "want", "was", "we", "well", "what", "when", "which",
    "who", "will", "with", "word", "work", "would", "write", "yes", "you", "your",
}

TARGET_NAME_HINTS = {
    "front", "target", "word", "expression", "vocabulary", "term", "phrase", "lemma",
    "plain word", "foreign", "question",
}
TRANSLATION_NAME_HINTS = {
    "back", "english", "translation", "meaning", "definition", "answer", "gloss", "native",
}
AUDIO_NAME_HINTS = {"audio", "sound", "pronunciation", "voice", "wordaudio"}


@dataclass(frozen=True)
class AutoConfigResult:
    target_field: str
    translation_field: str
    audio_field: str
    included_templates: Tuple[str, ...]
    recall_templates: Tuple[str, ...]
    included_card_count: int
    recall_card_count: int
    excluded_card_count: int
    inspected_card_count: int
    target_field_directly_on_question: bool

    @property
    def confident(self) -> bool:
        return bool(
            self.target_field
            and self.translation_field
            and (self.included_templates or self.recall_templates)
        )


def detect_deck_configuration(
    mw: Any,
    deck_name: str,
    learning_language: str,
    preferred_target_field: str = "",
    preferred_translation_field: str = "",
) -> AutoConfigResult:
    query = 'deck:"%s"' % str(deck_name or "").replace('"', '\\"')
    card_ids = list(mw.col.find_cards(query))[:MAX_INSPECTED_CARDS]
    cards: List[Tuple[Any, Any]] = []
    notes: Dict[Any, Any] = {}
    for card_id in card_ids:
        try:
            card = mw.col.get_card(card_id)
            note = card.note()
        except Exception:
            continue
        cards.append((card, note))
        note_key = getattr(note, "id", None)
        notes[note_key if note_key is not None else id(note)] = note

    fields = _ordered_fields(notes.values())
    samples = _field_samples(notes.values(), fields)
    target_field = _best_target_field(
        fields,
        samples,
        learning_language,
        preferred_target_field,
    )
    translation_field = _best_translation_field(
        fields,
        samples,
        target_field,
        preferred_translation_field,
    )
    audio_field = _best_audio_field(fields, samples)

    included_templates: Set[str] = set()
    recall_templates: Set[str] = set()
    included_count = 0
    recall_count = 0
    excluded_count = 0
    target_key = _field_key(target_field)
    translation_key = _field_key(translation_field)
    target_question_keys = _target_question_aliases(target_field, fields)
    direct_target_on_question = False
    for card, note in cards:
        question_fields = {
            _field_key(field)
            for field in visible_question_field_names(card_question_format(card, note))
        }
        if target_key and question_fields.intersection(target_question_keys):
            included_templates.add(card_template_name(card, note))
            included_count += 1
            if target_key in question_fields:
                direct_target_on_question = True
        elif translation_key and translation_key in question_fields:
            recall_templates.add(card_template_name(card, note))
            recall_count += 1
        else:
            excluded_count += 1

    return AutoConfigResult(
        target_field=target_field,
        translation_field=translation_field,
        audio_field=audio_field,
        included_templates=tuple(sorted(included_templates, key=str.casefold)),
        recall_templates=tuple(sorted(recall_templates, key=str.casefold)),
        included_card_count=included_count,
        recall_card_count=recall_count,
        excluded_card_count=excluded_count,
        inspected_card_count=len(cards),
        target_field_directly_on_question=direct_target_on_question,
    )


def auto_config_summary(
    result: AutoConfigResult,
    language_name: str,
    native_language_name: str = "English",
) -> str:
    if not result.confident:
        return "Auto-Configure could not identify a safe card direction. No settings were changed."
    return (
        "Detected %s %s to %s recognition cards and %s %s to %s recall cards. "
        "Excluded %s unclassified cards."
        % (
            format(result.included_card_count, ","),
            language_name,
            native_language_name,
            format(result.recall_card_count, ","),
            native_language_name,
            language_name,
            format(result.excluded_card_count, ","),
        )
    )


def _ordered_fields(notes: Iterable[Any]) -> List[str]:
    fields: List[str] = []
    seen = set()
    for note in notes:
        for field in note_field_names(note):
            key = _field_key(field)
            if key and key not in seen:
                seen.add(key)
                fields.append(field)
    return fields


def _field_samples(notes: Iterable[Any], fields: Sequence[str]) -> Dict[str, List[str]]:
    samples = {field: [] for field in fields}
    for note in notes:
        for field in fields:
            if len(samples[field]) >= 80:
                continue
            try:
                value = str(note[field] or "")
            except Exception:
                continue
            cleaned = re.sub(r"(?s)<[^>]+>", " ", html.unescape(value)).strip()
            if cleaned:
                samples[field].append(cleaned[:500])
    return samples


def _best_target_field(
    fields: Sequence[str],
    samples: Dict[str, List[str]],
    language: str,
    preferred: str,
) -> str:
    profile = get_language_profile(language)
    language_hints = {
        _field_key(language),
        _field_key(profile.code),
        _field_key(profile.name),
        _field_key(profile.tatoeba_code),
    }
    target_words = set(profile_ignored_words(language))

    def score(field: str) -> float:
        key = _field_key(field)
        value = 0.0
        if key in language_hints:
            value += 120
        if any(hint and hint in key for hint in language_hints):
            value += 70
        if key in TARGET_NAME_HINTS or any(hint in key for hint in TARGET_NAME_HINTS):
            value += 45
        if key in TRANSLATION_NAME_HINTS or any(hint in key for hint in TRANSLATION_NAME_HINTS):
            value -= 90
        if _field_key(preferred) == key:
            value += 12
        english_ratio, target_ratio = _language_ratios(samples.get(field, ()), target_words)
        if profile.code != "en":
            value += target_ratio * 80
            value -= english_ratio * 70
        return value

    return max(fields, key=score) if fields else ""


def _best_translation_field(
    fields: Sequence[str],
    samples: Dict[str, List[str]],
    target_field: str,
    preferred: str,
) -> str:
    candidates = [field for field in fields if _field_key(field) != _field_key(target_field)]
    maximum_sample_count = max(
        (len(samples.get(field, ())) for field in candidates),
        default=0,
    )

    def score(field: str) -> float:
        key = _field_key(field)
        value = 0.0
        if key in TRANSLATION_NAME_HINTS:
            value += 150
        elif any(hint in key for hint in TRANSLATION_NAME_HINTS):
            value += 70
        if key in AUDIO_NAME_HINTS or any(hint in key for hint in AUDIO_NAME_HINTS):
            value -= 100
        if _field_key(preferred) == key:
            value += 15
        if maximum_sample_count:
            value += 100 * len(samples.get(field, ())) / maximum_sample_count
        english_ratio, _target_ratio = _language_ratios(samples.get(field, ()), set())
        value += english_ratio * 70
        return value

    return max(candidates, key=score) if candidates else ""


def _best_audio_field(fields: Sequence[str], samples: Dict[str, List[str]]) -> str:
    def score(field: str) -> int:
        key = _field_key(field)
        value = 100 if key in AUDIO_NAME_HINTS or any(hint in key for hint in AUDIO_NAME_HINTS) else 0
        if any("[sound:" in sample.casefold() for sample in samples.get(field, ())):
            value += 150
        return value

    if not fields:
        return ""
    selected = max(fields, key=score)
    return selected if score(selected) > 0 else ""


def _language_ratios(samples: Sequence[str], target_words: Set[str]) -> Tuple[float, float]:
    tokens = [
        token.casefold()
        for sample in samples
        for token in re.findall(r"[^\W\d_]+", sample, flags=re.UNICODE)
    ]
    if not tokens:
        return 0.0, 0.0
    english = sum(token in ENGLISH_WORDS for token in tokens) / len(tokens)
    target = sum(token in target_words for token in tokens) / len(tokens) if target_words else 0.0
    return english, target


def _field_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _target_question_aliases(target_field: str, fields: Sequence[str]) -> Set[str]:
    target_key = _field_key(target_field)
    aliases = {target_key}
    for prefix in ("plain ", "clean ", "normalized "):
        if target_key.startswith(prefix):
            stripped = target_key[len(prefix) :]
            if any(_field_key(field) == stripped for field in fields):
                aliases.add(stripped)
    return aliases
