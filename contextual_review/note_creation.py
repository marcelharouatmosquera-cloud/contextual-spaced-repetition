"""Native Anki note creation for mined words and favorite sentences."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .config import ContextConfig
from .types import ReviewTask


FAVORITES_DECK_NAME = "Contextual Review Favorites"
FAVORITES_NOTETYPE_NAME = "Contextual Review Favorite"


@dataclass(frozen=True)
class MiningResult:
    note_id: int
    card_ids: Tuple[int, ...]
    audio_added: bool
    new_limit_increase: int


@dataclass(frozen=True)
class FavoritesExportResult:
    added: int
    skipped: int
    deck_name: str


def create_mined_note(
    mw: Any,
    task: ReviewTask,
    word: str,
    translation: str,
    config: ContextConfig,
    audio_path: Optional[Path] = None,
) -> MiningResult:
    """Create one note from the active task's exact note type and deck."""
    target_word = str(word or "").strip()
    meaning = str(translation or "").strip()
    if not target_word or not meaning:
        raise ValueError("Both the target word and its translation are required.")

    col = _collection(mw)
    source_card = _source_card_for_task(col, task)
    source_note = source_card.note()
    notetype = _note_type(source_note)
    deck_id = _source_deck_id(source_card)
    note = _new_note(col, notetype)
    field_names = _field_names(note)
    target_field = _resolve_field(field_names, config.target_field)
    if not target_field:
        raise RuntimeError(
            "The active note type does not contain the configured target field '%s'."
            % config.target_field
        )
    solution_field = _solution_field(field_names, config, target_field)
    if not solution_field:
        raise RuntimeError("The active note type has no configured translation field.")
    if _note_already_exists(col, notetype, deck_id, target_field, target_word):
        raise ValueError("Note already exists!")

    escaped_target = html.escape(target_word)
    note[target_field] = escaped_target
    for companion in _plain_display_companions(field_names, target_field):
        note[companion] = escaped_target
    note[solution_field] = html.escape(meaning)
    sentence_fields = _example_sentence_fields(
        field_names,
        excluded=(target_field, solution_field),
    )
    sentence_html = html.escape(str(task.full_text or "").strip())
    translation_html = html.escape(str(task.translation or "").strip())
    if sentence_fields and sentence_html:
        sentence_parts = _split_context_sentences(sentence_html, len(sentence_fields))
        translation_parts = _split_context_sentences(translation_html, len(sentence_fields))
        for index, (sentence_field, sentence_part) in enumerate(
            zip(sentence_fields, sentence_parts)
        ):
            note[sentence_field] = sentence_part
            for companion in _plain_display_companions(field_names, sentence_field):
                note[companion] = sentence_part
            translation_field = _sentence_translation_field(field_names, sentence_field)
            if translation_field and index < len(translation_parts):
                note[translation_field] = translation_parts[index]
    elif sentence_html:
        note[solution_field] += "<br><i>%s</i>" % sentence_html

    audio_added = False
    if audio_path is not None:
        audio_field = _audio_field(field_names, config, excluded=(target_field, solution_field))
        if audio_field:
            media_name = _add_media_file(col, audio_path)
            note[audio_field] = "[sound:%s]" % media_name
            audio_added = True

    new_limit_increase = 0
    undo_entry = _begin_undo(col, "Add Contextual Note")
    try:
        _add_note(col, note, deck_id)
        _merge_undo(col, undo_entry)
        card_ids = tuple(int(card_id) for card_id in col.card_ids_of_note(note.id))
        if not card_ids:
            raise RuntimeError(
                "The note type generated no cards. Check that its card templates use the mapped fields."
            )
        new_card_ids = [
            card_id for card_id in card_ids if int(getattr(col.get_card(card_id), "queue", -1)) == 0
        ]
        if new_card_ids:
            _reposition_new_cards_first(col, new_card_ids)
            _merge_undo(col, undo_entry)
            if config.increase_new_limit_after_mining:
                _extend_today_new_limit(col, deck_id, len(new_card_ids))
                new_limit_increase = len(new_card_ids)
                _merge_undo(col, undo_entry)
    except Exception:
        _rollback_undo(col)
        raise

    _refresh(mw)
    return MiningResult(int(note.id), card_ids, audio_added, new_limit_increase)


def export_favorites_to_anki(
    mw: Any,
    favorites: Sequence[Dict[str, Any]],
    deck_name: str = FAVORITES_DECK_NAME,
) -> FavoritesExportResult:
    """Copy stored favorites into a dedicated, undoable Anki deck."""
    col = _collection(mw)
    deck_id = _deck_id_for_name(col, deck_name)
    notetype = _favorite_notetype(col)
    existing = _existing_favorite_sentences(col, deck_name, notetype)
    skipped = 0
    pending: List[Dict[str, Any]] = []
    for favorite in favorites:
        sentence = str(favorite.get("text", "") or "").strip()
        key = _plain_text(sentence).casefold()
        if not sentence or key in existing:
            skipped += 1
            continue
        pending.append(favorite)
        existing.add(key)
    if not pending:
        return FavoritesExportResult(added=0, skipped=skipped, deck_name=deck_name)

    added = 0
    undo_entry = _begin_undo(col, "Export Contextual Review Favorites")
    try:
        for favorite in pending:
            sentence = str(favorite.get("text", "") or "").strip()
            note = _new_note(col, notetype)
            note["Sentence"] = html.escape(sentence)
            note["Translation"] = html.escape(
                str(favorite.get("translation", "") or "").strip()
            )
            note["Target Words"] = _favorite_target_words_html(
                favorite.get("target_words", ()) or ()
            )
            _add_note(col, note, deck_id)
            _merge_undo(col, undo_entry)
            added += 1
    except Exception:
        _rollback_undo(col)
        raise
    _refresh(mw)
    return FavoritesExportResult(added=added, skipped=skipped, deck_name=deck_name)


def _source_card_for_task(col: Any, task: ReviewTask) -> Any:
    card_ids: List[int] = []
    card_ids.extend(
        int(item.card_id)
        for item in (getattr(task, "target_words", ()) or ())
        if int(getattr(item, "card_id", 0) or 0)
    )
    for values in (getattr(task, "card_ids_by_key", {}) or {}).values():
        card_ids.extend(int(card_id) for card_id in values)
    for card_id in dict.fromkeys(card_ids):
        try:
            return col.get_card(card_id)
        except Exception:
            continue
    raise RuntimeError("The active sentence is not linked to an available Anki card.")


def _note_type(note: Any) -> Dict[str, Any]:
    getter = getattr(note, "note_type", None) or getattr(note, "model", None)
    if not callable(getter):
        raise RuntimeError("Anki could not read the active note type.")
    notetype = getter()
    if not isinstance(notetype, dict):
        raise RuntimeError("Anki returned an invalid note type.")
    return notetype


def _source_deck_id(card: Any) -> int:
    current_deck_id = getattr(card, "current_deck_id", None)
    if callable(current_deck_id):
        deck_id = int(current_deck_id() or 0)
    else:
        deck_id = int(getattr(card, "odid", 0) or getattr(card, "did", 0) or 0)
    if not deck_id:
        raise RuntimeError("Anki could not determine the source deck.")
    return deck_id


def _new_note(col: Any, notetype: Dict[str, Any]) -> Any:
    creator = getattr(col, "new_note", None)
    if not callable(creator):
        raise RuntimeError("This Anki version does not expose the native new_note() API.")
    return creator(notetype)


def _add_note(col: Any, note: Any, deck_id: int) -> None:
    adder = getattr(col, "add_note", None)
    if not callable(adder):
        raise RuntimeError("This Anki version does not expose the native add_note() API.")
    adder(note, deck_id)


def _field_names(note: Any) -> List[str]:
    try:
        return [str(name) for name in note.keys()]
    except Exception as exc:
        raise RuntimeError("Anki could not read the note's fields.") from exc


def _resolve_field(field_names: Iterable[str], requested: str) -> str:
    requested_key = str(requested or "").strip().casefold()
    return next((name for name in field_names if name.casefold() == requested_key), "")


def _solution_field(
    field_names: Sequence[str], config: ContextConfig, target_field: str
) -> str:
    candidates = [config.dictionary_field]
    candidates.extend(
        spec.field
        for spec in config.solution_fields
        if str(spec.display or "").casefold() != "audio"
    )
    for candidate in candidates:
        resolved = _resolve_field(field_names, candidate)
        if resolved and resolved.casefold() != target_field.casefold():
            return resolved
    return ""


def _audio_field(
    field_names: Sequence[str], config: ContextConfig, excluded: Sequence[str]
) -> str:
    excluded_keys = {name.casefold() for name in excluded}
    for spec in config.solution_fields:
        if str(spec.display or "").casefold() == "audio":
            resolved = _resolve_field(field_names, spec.field)
            if resolved and resolved.casefold() not in excluded_keys:
                return resolved
    for name in field_names:
        key = _field_label_key(name)
        if name.casefold() not in excluded_keys and any(
            token in key for token in ("audio", "sound", "pronunciation", "tts")
        ):
            return name
    return ""


def _example_sentence_fields(
    field_names: Sequence[str], excluded: Sequence[str]
) -> List[str]:
    excluded_keys = {name.casefold() for name in excluded}
    numbered: List[Tuple[int, str]] = []
    for name in field_names:
        if name.casefold() in excluded_keys:
            continue
        key = _field_label_key(name)
        match = re.fullmatch(r"(?:examplesentence|sentence|example|context)(\d+)", key)
        if match:
            numbered.append((int(match.group(1)), name))
    if numbered:
        return [name for _number, name in sorted(numbered)]

    for name in field_names:
        key = _field_label_key(name)
        if name.casefold() in excluded_keys:
            continue
        if any(
            token in key
            for token in (
                "examplesentence",
                "sentence",
                "example",
                "context",
                "satz",
                "beispiel",
                "frase",
                "oracion",
                "ejemplo",
                "phrase",
                "exemple",
                "contexte",
                "例文",
                "文脈",
            )
        ):
            return [name]
    return []


def _plain_display_companions(field_names: Sequence[str], field_name: str) -> List[str]:
    """Return paired visible/plain fields without guessing unrelated fields."""
    field_key = _field_label_key(field_name)
    companion_key = field_key[5:] if field_key.startswith("plain") else "plain" + field_key
    return [
        name
        for name in field_names
        if name.casefold() != field_name.casefold()
        and _field_label_key(name) == companion_key
    ]


def _sentence_translation_field(field_names: Sequence[str], sentence_field: str) -> str:
    base = re.sub(r"^plain\s*", "", sentence_field, flags=re.IGNORECASE).strip()
    candidates = (
        "%s Translation" % base,
        "Translation %s" % base,
        "Example Sentence Translation",
        "Sentence Translation",
        "Example Translation",
        "Context Translation",
    )
    for candidate in candidates:
        resolved = _resolve_field(field_names, candidate)
        if resolved:
            return resolved
    return ""


def _split_context_sentences(value: str, limit: int) -> List[str]:
    text = str(value or "").strip()
    if not text or limit <= 0:
        return []
    parts = [
        part.strip()
        for part in re.split(r"(?<=[.!?\u2026])\s+", text)
        if part.strip()
    ]
    if len(parts) <= limit:
        return parts
    return parts[: limit - 1] + [" ".join(parts[limit - 1 :])]


def _field_label_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", str(value or "").casefold(), flags=re.UNICODE)


def _note_already_exists(
    col: Any,
    notetype: Dict[str, Any],
    deck_id: int,
    target_field: str,
    target_word: str,
) -> bool:
    finder = getattr(col, "find_notes", None)
    if not callable(finder):
        raise RuntimeError("This Anki version does not expose the native note search API.")
    deck = col.decks.get(deck_id)
    deck_name = str(deck.get("name", "") or "") if isinstance(deck, dict) else ""
    notetype_name = str(notetype.get("name", "") or "")
    query = 'note:"%s" deck:"%s" "%s:%s"' % tuple(
        _search_escape(value)
        for value in (notetype_name, deck_name, target_field, target_word)
    )
    expected = _plain_text(target_word).casefold()
    for note_id in finder(query):
        try:
            existing = col.get_note(note_id)
            if _plain_text(existing[target_field]).casefold() == expected:
                return True
        except Exception:
            continue
    return False


def _search_escape(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"')


def _plain_text(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _add_media_file(col: Any, path: Path) -> str:
    add_file = getattr(getattr(col, "media", None), "add_file", None)
    if not callable(add_file):
        raise RuntimeError("This Anki version does not expose the native media API.")
    return str(add_file(str(path)))


def _reposition_new_cards_first(col: Any, card_ids: Sequence[int]) -> None:
    reposition = getattr(getattr(col, "sched", None), "reposition_new_cards", None)
    if not callable(reposition):
        raise RuntimeError("This Anki version does not expose native new-card repositioning.")
    reposition(
        card_ids=list(card_ids),
        starting_from=1,
        step_size=1,
        randomize=False,
        shift_existing=True,
    )


def _extend_today_new_limit(col: Any, deck_id: int, new_cards: int) -> None:
    """Temporarily add one New-card slot for each newly generated card."""
    if new_cards <= 0:
        return
    decks = getattr(col, "decks", None)
    current = getattr(decks, "current", None)
    select = getattr(decks, "select", None)
    extend_limits = getattr(getattr(col, "sched", None), "extend_limits", None)
    if not callable(current) or not callable(select) or not callable(extend_limits):
        raise RuntimeError(
            "This Anki version does not expose native temporary deck-limit controls."
        )
    current_deck = current()
    original_deck_id = (
        int(current_deck.get("id", 0) or 0) if isinstance(current_deck, dict) else 0
    )
    try:
        select(int(deck_id))
        extend_limits(int(new_cards), 0)
    finally:
        if original_deck_id:
            select(original_deck_id)


def _begin_undo(col: Any, label: str) -> int:
    add_undo = getattr(col, "add_custom_undo_entry", None)
    if not callable(add_undo):
        raise RuntimeError("This Anki version does not expose native undo grouping.")
    return int(add_undo(label))


def _merge_undo(col: Any, undo_entry: int) -> None:
    merge = getattr(col, "merge_undo_entries", None)
    if not callable(merge):
        raise RuntimeError("This Anki version does not expose native undo grouping.")
    merge(undo_entry)


def _rollback_undo(col: Any) -> None:
    undo = getattr(col, "undo", None)
    if callable(undo):
        undo()


def _collection(mw: Any) -> Any:
    col = getattr(mw, "col", None)
    if col is None:
        raise RuntimeError("Anki's collection is not available.")
    return col


def _refresh(mw: Any) -> None:
    reset = getattr(mw, "reset", None)
    if callable(reset):
        reset()


def _deck_id_for_name(col: Any, deck_name: str) -> int:
    decks = getattr(col, "decks", None)
    legacy_getter = getattr(decks, "id", None)
    if callable(legacy_getter):
        return int(legacy_getter(deck_name))
    creator = getattr(decks, "add_normal_deck_with_name", None)
    if callable(creator):
        return int(creator(deck_name).id)
    raise RuntimeError("Anki could not create the favorites deck.")


def _favorite_notetype(col: Any) -> Dict[str, Any]:
    manager = getattr(col, "models", None)
    by_name = getattr(manager, "by_name", None)
    if callable(by_name):
        existing = by_name(FAVORITES_NOTETYPE_NAME)
        if existing:
            return existing
    required = ("new", "new_field", "add_field", "new_template", "add_template", "add")
    if not manager or not all(callable(getattr(manager, name, None)) for name in required):
        raise RuntimeError("Anki could not create the favorites note type.")
    notetype = manager.new(FAVORITES_NOTETYPE_NAME)
    for field_name in ("Sentence", "Translation", "Target Words"):
        manager.add_field(notetype, manager.new_field(field_name))
    template = manager.new_template("Favorite Sentence")
    template["qfmt"] = "{{Sentence}}"
    template["afmt"] = "{{FrontSide}}<hr id=answer>{{Translation}}<br>{{Target Words}}"
    manager.add_template(notetype, template)
    manager.add(notetype)
    return notetype


def _existing_favorite_sentences(
    col: Any, deck_name: str, notetype: Dict[str, Any]
) -> set[str]:
    finder = getattr(col, "find_notes", None)
    if not callable(finder):
        return set()
    query = 'deck:"%s" note:"%s"' % (
        _search_escape(deck_name),
        _search_escape(str(notetype.get("name", "") or "")),
    )
    existing: set[str] = set()
    for note_id in finder(query):
        try:
            existing.add(_plain_text(col.get_note(note_id)["Sentence"]).casefold())
        except Exception:
            continue
    return existing


def _favorite_target_words_html(values: Iterable[Any]) -> str:
    rows = []
    for value in values:
        if not isinstance(value, dict):
            continue
        word = str(value.get("word", "") or "").strip()
        definition = str(value.get("definition", "") or "").strip()
        if not word:
            continue
        row = "<b>%s</b>" % html.escape(word)
        if definition:
            row += ": %s" % html.escape(definition)
        rows.append(row)
    return "<br>".join(rows)
