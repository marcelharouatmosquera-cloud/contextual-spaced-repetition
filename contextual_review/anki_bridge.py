"""Small Anki API adapter used by the contextual reviewer."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .config import ContextConfig
from .debug_log import append_debug_log
from .normalizer import (
    matching_key_for_word,
    normalize_form,
    normalize_word,
    select_target_tokens,
)
from .template_fields import visible_question_field_names
from .types import DueCard, ReviewTask, SolutionFieldValue

class DueCardCollection(list):
    """Limited selection rows plus the full set of eligible cards due today."""

    def __init__(self, values: Iterable[DueCard], today_card_ids: Iterable[int]) -> None:
        super().__init__(values)
        self.today_card_ids = frozenset(int(card_id) for card_id in today_card_ids)


@dataclass(frozen=True)
class CardAnswer:
    card_id: int
    ease: int
    match_keys: List[str]
    is_unknown: bool


@dataclass(frozen=True)
class AnswerSummary:
    answered_card_ids: List[int]
    unknown_card_ids: List[int]
    known_card_ids: List[int]
    completed_card_ids: Optional[List[int]] = None
    learning_card_ids: Optional[List[int]] = None


def build_due_search_query(mw: Any, config: ContextConfig) -> str:
    due_query = config.custom_search_query.strip() or "is:due"
    new_filter = _custom_filter_without_due(due_query)
    new_query = "is:new%s" % (" " + new_filter if new_filter else "")
    if config.include_due_cards and config.include_new_cards:
        query = "((%s) OR (%s))" % (due_query, new_query)
    elif config.include_new_cards:
        query = new_query
    elif config.include_due_cards:
        query = due_query
    else:
        query = "nid:0"
    if not config.include_new_cards and "-is:new" not in query:
        query = "(%s) -is:new" % query

    return _scope_query(mw, config, "(%s) -is:buried" % query)


def build_future_search_query(mw: Any, config: ContextConfig) -> str:
    extra_filter = _custom_filter_without_due(config.custom_search_query)
    query = "prop:due<=%s" % int(config.future_due_days)
    if extra_filter:
        query = "%s %s" % (query, extra_filter)
    if not config.include_new_cards:
        query = "(%s) -is:new" % query
    if not config.include_learning_cards:
        query = "(%s) -is:learn" % query
    return _scope_query(mw, config, "(%s) -is:buried" % query)


def _custom_filter_without_due(query: str) -> str:
    parts = _split_search_terms(str(query or ""))
    kept = [part for part in parts if part.lower() != "is:due"]
    return " ".join(kept)


def _split_search_terms(query: str) -> List[str]:
    terms: List[str] = []
    current: List[str] = []
    quote = ""
    escaped = False

    for char in query:
        if escaped:
            current.append(char)
            escaped = False
            continue

        if quote:
            current.append(char)
            if char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue

        if char in {'"', "'"}:
            quote = char
            current.append(char)
        elif char.isspace():
            if current:
                terms.append("".join(current))
                current = []
        else:
            current.append(char)

    if current:
        terms.append("".join(current))
    return [term for term in terms if term.strip()]


def _scope_query(mw: Any, config: ContextConfig, query: str) -> str:
    if config.deck_scope == "configured" and config.deck_name.strip():
        escaped = config.deck_name.strip().replace('"', '\\"')
        return '%s deck:"%s"' % (query, escaped)

    if config.deck_scope != "current":
        return query

    deck_name = ""
    try:
        deck = mw.col.decks.get(mw.col.decks.selected())
        deck_name = deck.get("name", "")
    except Exception:
        deck_name = ""

    if not deck_name:
        return query

    escaped = deck_name.replace('"', '\\"')
    return '%s deck:"%s"' % (query, escaped)


def collect_due_cards(mw: Any, config: ContextConfig) -> List[DueCard]:
    due_query = build_due_search_query(mw, config)
    future_query = ""
    try:
        card_ids = list(mw.col.find_cards(due_query))
    except Exception as exc:
        append_debug_log("collect_due_cards_error", query=due_query, error=str(exc))
        raise
    due_search_count = len(card_ids)
    today_search_card_ids = set(_unique_ids(card_ids))
    if config.include_due_cards and config.future_due_days > 0:
        future_query = build_future_search_query(mw, config)
        try:
            future_ids = list(mw.col.find_cards(future_query))
        except Exception as exc:
            append_debug_log("collect_due_cards_error", query=future_query, error=str(exc))
            raise
        card_ids.extend(future_ids)
    else:
        future_ids = []
    card_ids = _unique_ids(card_ids)

    note_type_filter = set(config.note_types)
    today = int(getattr(getattr(mw.col, "sched", None), "today", 0) or 0)
    now = int(time.time())
    due_cards: List[DueCard] = []
    skipped: Dict[str, int] = {}
    accepted_new_card_ids: Set[int] = set()

    for card_id in card_ids:
        try:
            card = mw.col.get_card(card_id)
            note = card.note()
        except Exception:
            _increment_skip(skipped, "load_error")
            continue

        if _card_is_in_filtered_deck(mw, card_id, card):
            _increment_skip(skipped, "filtered_deck")
            continue
        if not _card_allowed(card, config):
            _increment_skip(skipped, "card_state")
            continue
        if _intraday_learning_step_is_early(card, now):
            # Anki's is:due search may include queue-1 cards inside the
            # learn-ahead window. Contextual Review promises the displayed
            # learning delay, so do not admit them before their exact timestamp.
            _increment_skip(skipped, "learning_delay")
            continue
        if not _card_in_review_window(card, today, config.future_due_days):
            _increment_skip(skipped, "future_window")
            continue

        note_type = _note_type_name(note)
        if note_type_filter and note_type not in note_type_filter:
            _increment_skip(skipped, "note_type")
            continue
        direction, template_allowed = _card_review_direction(card, note, config)
        if not template_allowed:
            _increment_skip(skipped, "card_template")
            continue

        field_value = _field_value(note, config.target_field)
        if not field_value:
            _increment_skip(skipped, "target_field")
            continue
        solution_fields = _solution_field_values(mw, note, config)
        excluded_hint_field = config.target_field if direction == "recall" else ""
        plain_definition = _first_text_solution(
            solution_fields,
            excluded_field=excluded_hint_field,
        )
        if not plain_definition:
            definition_value = _definition_value(note, config)
            plain_definition = html.unescape(_strip_html(definition_value)) if definition_value else ""
        if direction == "recall" and not plain_definition.strip():
            # Never fall back to the target field itself: that would put the
            # answer inside the recall hint box.
            _increment_skip(skipped, "recall_hint")
            continue
        if (
            direction != "recall"
            and config.require_target_on_question
            and not _card_question_contains_field(
                card,
                note,
                config.target_field,
            )
        ):
            _increment_skip(skipped, "target_not_on_question")
            continue
        if _card_is_new(card) and card_id not in accepted_new_card_ids:
            if len(accepted_new_card_ids) >= config.max_new_cards:
                _increment_skip(skipped, "new_card_limit")
                continue
            accepted_new_card_ids.add(card_id)

        plain_value = html.unescape(_strip_html(field_value))
        seen_keys: Set[str] = set()
        interval = _int_attr(card, "ivl", 0)
        factor = _int_attr(card, "factor", 2500)
        overdue, due_in_days, priority = _due_metrics(card, today)
        is_learning_due = card_id in today_search_card_ids and _card_is_learning(card)
        if is_learning_due:
            # A due intraday step should win the next sentence selection instead
            # of waiting behind a cache-sized batch of overdue review cards.
            priority += 1000.0
        target_display = _target_display_text(plain_value)
        note_id = _int_attr(card, "nid", 0) or _int_attr(note, "id", 0)
        for token in select_target_tokens(
            plain_value,
            config.language,
            config.target_extraction_mode,
            config.ignored_target_words,
        ):
            lemma = normalize_word(token.text, config.language)
            word_form = normalize_form(token.text)
            match_key = matching_key_for_word(token.text, config.language, config.matching_mode)
            if not match_key or match_key in seen_keys:
                continue
            seen_keys.add(match_key)
            due_cards.append(
                DueCard(
                    card_id=int(card_id),
                    target_word=target_display or token.text,
                    lemma=lemma,
                    definition=plain_definition,
                    solution_fields=solution_fields,
                    word_form=word_form,
                    match_key=match_key,
                    interval=interval,
                    factor=factor,
                    overdue=overdue,
                    due_in_days=due_in_days,
                    priority=priority,
                    is_learning_due=is_learning_due,
                    direction=direction,
                    note_id=note_id,
                )
            )

    unfiltered_due_cards = sorted(due_cards, key=_due_card_sort_key)
    direction_filtered_due_cards = _defer_recall_siblings(unfiltered_due_cards)
    deferred_recall_card_ids = sorted(
        {card.card_id for card in unfiltered_due_cards}
        - {card.card_id for card in direction_filtered_due_cards}
    )
    if deferred_recall_card_ids:
        skipped["recall_after_recognition"] = len(deferred_recall_card_ids)
    sorted_due_cards = _filter_sibling_due_cards(mw, direction_filtered_due_cards, today)
    suppressed_sibling_card_ids = sorted(
        {card.card_id for card in direction_filtered_due_cards}
        - {card.card_id for card in sorted_due_cards}
    )
    if suppressed_sibling_card_ids:
        skipped["sibling_bury"] = len(suppressed_sibling_card_ids)
    limited_due_cards = _limit_due_card_targets(sorted_due_cards, config.max_due_cards)
    append_debug_log(
        "collect_due_cards",
        due_query=due_query,
        future_query=future_query,
        due_search_count=due_search_count,
        future_search_count=len(future_ids),
        unique_card_count=len(card_ids),
        collected_target_count=len(sorted_due_cards),
        returned_target_count=len(limited_due_cards),
        returned_card_ids=sorted({card.card_id for card in limited_due_cards}),
        deferred_recall_card_ids=deferred_recall_card_ids,
        suppressed_sibling_card_ids=suppressed_sibling_card_ids,
        skipped=skipped,
        today=today,
        future_due_days=config.future_due_days,
    )
    eligible_today_card_ids = {
        card.card_id
        for card in sorted_due_cards
        if card.card_id in today_search_card_ids
    }
    return DueCardCollection(limited_due_cards, eligible_today_card_ids)


def _defer_recall_siblings(due_cards: Sequence[DueCard]) -> List[DueCard]:
    """Keep recognition ahead of a due recall sibling from the same note."""
    directions_by_note: Dict[int, Set[str]] = {}
    for card in due_cards:
        note_id = int(card.note_id or 0)
        if not note_id:
            continue
        directions_by_note.setdefault(note_id, set()).add(_normalized_direction(card.direction))
    mixed_note_ids = {
        note_id
        for note_id, directions in directions_by_note.items()
        if directions == {"recognition", "recall"}
    }
    if not mixed_note_ids:
        return list(due_cards)
    return [
        card
        for card in due_cards
        if not (
            int(card.note_id or 0) in mixed_note_ids
            and _normalized_direction(card.direction) == "recall"
        )
    ]


def _filter_sibling_due_cards(
    mw: Any, due_cards: Sequence[DueCard], today: int
) -> List[DueCard]:
    """Mirror Anki's queue-time sibling suppression for the contextual queue."""
    col = getattr(mw, "col", None)
    if col is None:
        return list(due_cards)

    modes_by_note: Dict[int, Tuple[bool, bool, bool]] = {}
    allowed_card_ids: Set[int] = set()
    processed_card_ids: Set[int] = set()
    for due_card in due_cards:
        card_id = int(due_card.card_id)
        if card_id in processed_card_ids:
            continue
        processed_card_ids.add(card_id)
        try:
            card = col.get_card(card_id)
        except Exception:
            allowed_card_ids.add(card_id)
            continue
        note_id = _int_attr(card, "nid", 0)
        if not note_id:
            allowed_card_ids.add(card_id)
            continue

        previous_mode = modes_by_note.get(note_id)
        new_mode = _sibling_bury_mode_for_card(col, card)
        if previous_mode is None:
            allowed_card_ids.add(card_id)
            modes_by_note[note_id] = new_mode
            continue

        if not _sibling_card_is_suppressed(card, previous_mode, today):
            allowed_card_ids.add(card_id)
        modes_by_note[note_id] = tuple(
            previous or new for previous, new in zip(previous_mode, new_mode)
        )

    return [card for card in due_cards if int(card.card_id) in allowed_card_ids]


def _sibling_card_is_suppressed(
    card: Any, mode: Tuple[bool, bool, bool], today: int
) -> bool:
    bury_new, bury_reviews, bury_interday = mode
    queue = _card_queue(card)
    if queue == 0:
        return bury_new
    if queue == 2 and _int_attr(card, "due", today) <= today:
        return bury_reviews
    if queue == 3 and _int_attr(card, "due", today) <= today:
        return bury_interday
    # Anki does not sibling-bury intraday queue-1 learning cards.
    return False


def _limit_due_card_targets(due_cards: Sequence[DueCard], max_cards: int) -> List[DueCard]:
    """Keep every target from the highest-priority distinct cards.

    A note field may contain multiple target words. Counting those rows against
    ``max_due_cards`` could let one phrase crowd every other card out.
    """
    selected_card_ids: Set[int] = set()
    allowed_card_ids: Set[int] = set()
    limit = max(1, int(max_cards or 1))
    for card in due_cards:
        card_id = int(card.card_id)
        if card_id in selected_card_ids:
            continue
        selected_card_ids.add(card_id)
        allowed_card_ids.add(card_id)
        if len(allowed_card_ids) >= limit:
            break
    return [card for card in due_cards if int(card.card_id) in allowed_card_ids]


def _target_display_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def answer_review_task(
    mw: Any,
    task: ReviewTask,
    unknown_keys: Iterable[str],
    config: ContextConfig,
    unknown_card_ids: Iterable[Any] = (),
) -> AnswerSummary:
    unknown_key_list = [str(key) for key in unknown_keys if str(key)]
    unknown_card_id_list = [str(card_id) for card_id in unknown_card_ids if str(card_id)]
    answers = build_answer_plan(
        task,
        unknown_key_list,
        config,
        unknown_card_ids=unknown_card_id_list,
    )
    if not answers:
        append_debug_log(
            "answer_review_task_no_cards",
            sentence_id=task.sentence_id,
            unknown_keys=unknown_key_list,
            unknown_card_ids=unknown_card_id_list,
            card_ids_by_key=task.card_ids_by_key,
        )
        return AnswerSummary([], [], [], completed_card_ids=[], learning_card_ids=[])

    answer_card_ids = [answer.card_id for answer in answers]
    append_debug_log(
        "answer_review_task_start",
        sentence_id=task.sentence_id,
        unknown_keys=unknown_key_list,
        unknown_card_ids=unknown_card_id_list,
        answers=_debug_answer_plan(answers),
        before=_debug_card_states(mw, answer_card_ids),
    )

    try:
        summary = _with_completed_card_ids(
            mw,
            _answer_with_anki_grade_now(mw, answers),
        )
        append_debug_log(
            "answer_review_task_success",
            scheduler="anki_grade_now",
            sentence_id=task.sentence_id,
            summary=_debug_answer_summary(summary),
            after=_debug_card_states(mw, answer_card_ids),
        )
        return summary
    except Exception as exc:
        append_debug_log(
            "answer_review_task_error",
            scheduler="anki_grade_now",
            sentence_id=task.sentence_id,
            error=str(exc),
            after=_debug_card_states(mw, answer_card_ids),
        )
        raise


def _answer_with_anki_grade_now(mw: Any, answers: Sequence[CardAnswer]) -> AnswerSummary:
    """Grade arbitrary cards with Anki's real scheduler as one undo action."""
    col = getattr(mw, "col", None)
    backend = getattr(col, "_backend", None)
    grade_now = getattr(backend, "grade_now", None)
    add_undo = getattr(col, "add_custom_undo_entry", None)
    merge_undo = getattr(col, "merge_undo_entries", None)
    undo = getattr(col, "undo", None)
    if not all(callable(item) for item in (grade_now, add_undo, merge_undo, undo)):
        raise RuntimeError(
            "Anki's native grade_now batch API is unavailable. Run Contextual Review Diagnostics."
        )

    cards = _load_cards_for_answers(mw, answers)
    sibling_card_ids = _sibling_card_ids_to_bury(mw, answers, cards)
    undo_entry = add_undo("Contextual Review")
    try:
        answers_by_rating: Dict[int, List[int]] = {}
        for answer in answers:
            rating = _grade_now_rating_for_ease(answer.ease)
            answers_by_rating.setdefault(rating, []).append(int(answer.card_id))
        for rating, card_ids in sorted(answers_by_rating.items()):
            grade_now(card_ids=card_ids, rating=rating)
            merge_undo(undo_entry)
        if sibling_card_ids:
            bury_cards = getattr(getattr(col, "sched", None), "bury_cards", None)
            if not callable(bury_cards):
                raise RuntimeError("Anki's scheduler sibling-bury API is unavailable.")
            bury_cards(sibling_card_ids, manual=False)
            merge_undo(undo_entry)
    except Exception as exc:
        try:
            # If grading failed, this removes either the failed operation's
            # custom entry or the already-merged part of the sentence.
            undo()
        except Exception as undo_exc:
            raise RuntimeError(
                "Anki could not grade the contextual cards, and rollback also failed: %s"
                % undo_exc
            ) from exc
        _flush_collection(mw)
        raise RuntimeError("Anki could not grade the contextual cards: %s" % exc) from exc

    _flush_collection(mw)
    if sibling_card_ids:
        append_debug_log(
            "answer_review_task_siblings_buried",
            answered_card_ids=[answer.card_id for answer in answers],
            buried_sibling_card_ids=sibling_card_ids,
        )
    return AnswerSummary(
        answered_card_ids=[answer.card_id for answer in answers],
        unknown_card_ids=[answer.card_id for answer in answers if answer.is_unknown],
        known_card_ids=[answer.card_id for answer in answers if not answer.is_unknown],
    )


def _grade_now_rating_for_ease(ease: Any) -> int:
    """Translate Anki's reviewer ease 1..4 to Grade Now's rating 0..3."""
    try:
        parsed = int(ease)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Invalid Anki answer ease: %s" % ease) from exc
    if parsed not in (1, 2, 3, 4):
        raise RuntimeError("Invalid Anki answer ease: %s" % ease)
    return parsed - 1


def _sibling_card_ids_to_bury(
    mw: Any,
    answers: Sequence[CardAnswer],
    cards: Dict[int, Any],
) -> List[int]:
    """Return due sibling cards covered by each answered card's deck options."""
    col = getattr(mw, "col", None)
    if col is None:
        return []
    answered_card_ids = {int(answer.card_id) for answer in answers}
    modes_by_note: Dict[int, Tuple[bool, bool, bool]] = {}
    for answer in answers:
        card = cards.get(int(answer.card_id))
        note_id = _int_attr(card, "nid", 0)
        if not note_id:
            continue
        bury_new, bury_reviews, bury_interday = _sibling_bury_mode_for_card(col, card)
        previous = modes_by_note.get(note_id, (False, False, False))
        modes_by_note[note_id] = (
            previous[0] or bury_new,
            previous[1] or bury_reviews,
            previous[2] or bury_interday,
        )

    today = int(getattr(getattr(col, "sched", None), "today", 0) or 0)
    sibling_card_ids: Set[int] = set()
    card_ids_of_note = getattr(col, "card_ids_of_note", None)
    for note_id, (bury_new, bury_reviews, bury_interday) in modes_by_note.items():
        try:
            note_card_ids = list(card_ids_of_note(note_id)) if callable(card_ids_of_note) else []
        except Exception:
            note_card_ids = []
        for sibling_id in _unique_ids(note_card_ids):
            if sibling_id in answered_card_ids:
                continue
            try:
                sibling = col.get_card(sibling_id)
            except Exception:
                continue
            if _int_attr(sibling, "odid", 0) or _card_queue(sibling) < 0:
                continue
            queue = _card_queue(sibling)
            if queue == 0 and bury_new:
                sibling_card_ids.add(sibling_id)
            elif queue == 2 and bury_reviews and _int_attr(sibling, "due", today) <= today:
                sibling_card_ids.add(sibling_id)
            elif queue == 3 and bury_interday and _int_attr(sibling, "due", today) <= today:
                sibling_card_ids.add(sibling_id)
    return sorted(sibling_card_ids)


def _sibling_bury_mode_for_card(col: Any, card: Any) -> Tuple[bool, bool, bool]:
    try:
        current_deck_id = getattr(card, "current_deck_id", None)
        deck_id = current_deck_id() if callable(current_deck_id) else (
            _int_attr(card, "odid", 0) or _int_attr(card, "did", 0)
        )
        config = col.decks.config_dict_for_deck_id(deck_id)
    except Exception:
        return False, False, False
    new_config = config.get("new", {}) if isinstance(config, dict) else {}
    review_config = config.get("rev", {}) if isinstance(config, dict) else {}
    return (
        bool(new_config.get("bury", False)),
        bool(review_config.get("bury", False)),
        bool(config.get("buryInterdayLearning", False)),
    )


def build_answer_plan(
    task: ReviewTask,
    unknown_keys: Iterable[str],
    config: ContextConfig,
    unknown_card_ids: Iterable[Any] = (),
) -> List[CardAnswer]:
    unknown_set = {str(key) for key in unknown_keys if str(key)}
    explicit_unknown_card_ids = {
        parsed
        for parsed in (_safe_card_id(card_id) for card_id in unknown_card_ids)
        if parsed is not None
    }
    card_keys: Dict[int, Set[str]] = {}
    planned_unknown_card_ids: Set[int] = set()

    for match_key, card_ids in task.card_ids_by_key.items():
        cleaned_key = str(match_key or "")
        for card_id in card_ids:
            parsed = _safe_card_id(card_id)
            if parsed is None:
                continue
            card_keys.setdefault(parsed, set()).add(cleaned_key)
            if cleaned_key in unknown_set or parsed in explicit_unknown_card_ids:
                planned_unknown_card_ids.add(parsed)

    answers: List[CardAnswer] = []
    for card_id in sorted(card_keys):
        is_unknown = card_id in planned_unknown_card_ids
        answers.append(
            CardAnswer(
                card_id=card_id,
                ease=config.unknown_ease if is_unknown else config.known_ease,
                match_keys=sorted(key for key in card_keys[card_id] if key),
                is_unknown=is_unknown,
            )
        )
    return answers


def _increment_skip(skipped: Dict[str, int], reason: str) -> None:
    skipped[reason] = skipped.get(reason, 0) + 1


def _debug_answer_plan(answers: Sequence[CardAnswer]) -> List[Dict[str, Any]]:
    return [
        {
            "card_id": answer.card_id,
            "ease": answer.ease,
            "is_unknown": answer.is_unknown,
            "match_keys": answer.match_keys,
        }
        for answer in answers
    ]


def _debug_answer_summary(summary: AnswerSummary) -> Dict[str, Any]:
    return {
        "answered_card_ids": summary.answered_card_ids,
        "unknown_card_ids": summary.unknown_card_ids,
        "known_card_ids": summary.known_card_ids,
        "completed_card_ids": list(summary.completed_card_ids or ()),
        "learning_card_ids": list(summary.learning_card_ids or ()),
    }


def _with_completed_card_ids(mw: Any, summary: AnswerSummary) -> AnswerSummary:
    """Mark Good cards complete only when their next step leaves today's lesson."""
    known_card_ids = _unique_ids(summary.known_card_ids)
    answered_card_ids = _unique_ids(summary.answered_card_ids)
    states = {
        int(state["card_id"]): state
        for state in _debug_card_states(mw, answered_card_ids)
        if state.get("card_id") is not None
    }
    today = int(getattr(getattr(getattr(mw, "col", None), "sched", None), "today", 0) or 0)
    completed_card_ids = [
        card_id
        for card_id in known_card_ids
        if _card_state_is_beyond_current_lesson(states.get(card_id), today)
    ]
    learning_card_ids = [
        card_id
        for card_id in answered_card_ids
        if _card_state_is_intraday_learning(states.get(card_id))
    ]
    return AnswerSummary(
        answered_card_ids=list(summary.answered_card_ids),
        unknown_card_ids=list(summary.unknown_card_ids),
        known_card_ids=list(summary.known_card_ids),
        completed_card_ids=completed_card_ids,
        learning_card_ids=learning_card_ids,
    )


def _card_state_is_intraday_learning(state: Optional[Dict[str, Any]]) -> bool:
    if not state or state.get("error"):
        return False
    try:
        return int(state.get("queue")) == 1
    except (TypeError, ValueError):
        return False


def _card_state_is_beyond_current_lesson(
    state: Optional[Dict[str, Any]],
    today: int,
) -> bool:
    if not state or state.get("error"):
        return False
    try:
        queue = int(state.get("queue"))
        due = int(state.get("due"))
    except (TypeError, ValueError):
        return False

    # Queue 1 is an intraday learning/relearning step. Queue 2 is a normal
    # review, and queue 3 is a day-based learning step; the latter two have
    # left today's lesson only when their next due day is after today.
    return queue in (2, 3) and due > int(today)


def _debug_card_states(mw: Any, card_ids: Sequence[int]) -> List[Dict[str, Any]]:
    db = _collection_db(mw)
    rows: Dict[int, Dict[str, Any]] = {}
    if db is not None:
        try:
            rows = _read_card_rows(db, card_ids)
        except Exception:
            rows = {}

    states: List[Dict[str, Any]] = []
    for card_id in card_ids:
        row = rows.get(int(card_id))
        if row is not None:
            states.append(
                {
                    "card_id": int(card_id),
                    "source": "db",
                    "type": row.get("type"),
                    "queue": row.get("queue"),
                    "due": row.get("due"),
                    "ivl": row.get("ivl"),
                    "factor": row.get("factor"),
                    "reps": row.get("reps"),
                    "lapses": row.get("lapses"),
                    "left": row.get("left"),
                    "odue": row.get("odue"),
                    "odid": row.get("odid"),
                }
            )
            continue

        state: Dict[str, Any] = {"card_id": int(card_id), "source": "card"}
        try:
            card = mw.col.get_card(card_id)
            for attr in ("type", "queue", "due", "ivl", "factor", "reps", "lapses", "left", "odue", "odid"):
                try:
                    state[attr] = getattr(card, attr, None)
                except Exception:
                    state[attr] = None
        except Exception as exc:
            state["error"] = str(exc)
        states.append(state)
    return states


CARD_COLUMNS = (
    "id",
    "nid",
    "did",
    "ord",
    "mod",
    "usn",
    "type",
    "queue",
    "due",
    "ivl",
    "factor",
    "reps",
    "lapses",
    "left",
    "odue",
    "odid",
    "flags",
    "data",
)


def _collection_db(mw: Any) -> Any:
    return getattr(getattr(mw, "col", None), "db", None)


def _read_card_rows(db: Any, card_ids: Sequence[int]) -> Dict[int, Dict[str, Any]]:
    rows: Dict[int, Dict[str, Any]] = {}
    unique_card_ids = _unique_ids(card_ids)
    if not unique_card_ids:
        return rows
    placeholders = ", ".join("?" for _ in unique_card_ids)
    sql = "SELECT %s FROM cards WHERE id IN (%s)" % (
        ", ".join(CARD_COLUMNS),
        placeholders,
    )
    for row in _db_all(db, sql, unique_card_ids):
        values = dict(row) if hasattr(row, "keys") else dict(zip(CARD_COLUMNS, row))
        rows[int(values["id"])] = values
    return rows


def _db_first(db: Any, sql: str, params: Sequence[Any]) -> Any:
    first = getattr(db, "first", None)
    if callable(first):
        return first(sql, *params)
    cursor = db.execute(sql, tuple(params))
    return cursor.fetchone()


def _db_all(db: Any, sql: str, params: Sequence[Any]) -> Sequence[Any]:
    all_rows = getattr(db, "all", None)
    if callable(all_rows):
        return all_rows(sql, *params)
    cursor = db.execute(sql, tuple(params))
    return cursor.fetchall()


def _load_cards_for_answers(mw: Any, answers: Sequence[CardAnswer]) -> Dict[int, Any]:
    cards: Dict[int, Any] = {}
    missing: List[int] = []
    for answer in answers:
        try:
            cards[answer.card_id] = mw.col.get_card(answer.card_id)
        except Exception:
            missing.append(answer.card_id)
    if missing:
        raise RuntimeError("Could not load card(s): %s" % ", ".join(str(card_id) for card_id in missing))
    return cards


def _flush_collection(mw: Any) -> None:
    try:
        mw.col.update()
    except Exception:
        try:
            mw.col.save()
        except Exception:
            pass

    try:
        mw.reset()
    except Exception:
        pass


def _field_value(note: Any, field_name: str) -> str:
    keys = _note_field_names(note)
    requested = _field_name_key(field_name)
    matched_field = field_name if field_name in keys else ""
    if not matched_field:
        for key in keys:
            if _field_name_key(key) == requested:
                matched_field = key
                break

    if matched_field:
        try:
            return str(note[matched_field])
        except Exception:
            return ""
    return ""


def _definition_value(note: Any, config: ContextConfig) -> str:
    target_key = _field_name_key(config.target_field)
    preferred = [
        config.dictionary_field,
        "Back",
        "Definition",
        "Meaning",
        "Translation",
        "English",
        "Native",
        "Answer",
    ]
    checked: Set[str] = set()
    for field_name in preferred:
        key = _field_name_key(field_name)
        if not key or key == target_key or key in checked:
            continue
        checked.add(key)
        value = _field_value(note, field_name)
        if value.strip():
            return value

    for field_name in _note_field_names(note):
        key = _field_name_key(field_name)
        if key == target_key or key in checked:
            continue
        value = _field_value(note, field_name)
        if value.strip():
            return value
    return ""


def _solution_field_values(
    mw: Any, note: Any, config: ContextConfig
) -> Tuple[SolutionFieldValue, ...]:
    values: List[SolutionFieldValue] = []
    for spec in config.solution_fields:
        raw = _field_value(note, spec.field)
        if not str(raw or "").strip():
            continue
        display = _resolved_solution_display(spec.display, raw)
        text = ""
        media: Tuple[str, ...] = ()
        if display == "image":
            media = tuple(_resolved_image_sources(mw, _image_sources(raw)))
            if not media:
                text = html.unescape(_strip_html(raw))
        elif display == "audio":
            media = tuple(_audio_sources(raw))
            if not media:
                text = html.unescape(_strip_html(raw))
        else:
            text = html.unescape(_strip_html(raw))
        values.append(
            SolutionFieldValue(
                field=spec.field,
                label=spec.label or spec.field,
                display=display,
                text=text.strip(),
                media=media,
                autoplay=bool(spec.autoplay and display == "audio"),
            )
        )
    return tuple(values)


def _first_text_solution(
    values: Sequence[SolutionFieldValue], excluded_field: str = ""
) -> str:
    excluded_key = _field_name_key(excluded_field)
    for value in values:
        if excluded_key and _field_name_key(value.field) == excluded_key:
            continue
        if value.text.strip():
            return value.text.strip()
    return ""


def _resolved_solution_display(display: str, raw: str) -> str:
    requested = str(display or "auto").strip().lower()
    if requested in {"text", "image", "audio"}:
        return requested
    if _audio_sources(raw):
        return "audio"
    if _image_sources(raw):
        return "image"
    return "text"


def _image_sources(raw: str) -> List[str]:
    return _unique_media_sources(
        match.group(2)
        for match in re.finditer(
            r"""<img\b[^>]*\bsrc\s*=\s*(["'])(.*?)\1""",
            str(raw or ""),
            re.IGNORECASE | re.DOTALL,
        )
    )


def _audio_sources(raw: str) -> List[str]:
    text = str(raw or "")
    sources = [match.group(1) for match in re.finditer(r"\[sound:([^\]]+)\]", text, re.IGNORECASE)]
    sources.extend(
        match.group(2)
        for match in re.finditer(
            r"""<(?:audio|source)\b[^>]*\bsrc\s*=\s*(["'])(.*?)\1""",
            text,
            re.IGNORECASE | re.DOTALL,
        )
    )
    return _unique_media_sources(sources)


def _unique_media_sources(sources: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for source in sources:
        cleaned = html.unescape(str(source or "").strip())
        if not cleaned or cleaned in seen:
            continue
        if re.match(r"(?i)^\s*(?:javascript|data:text/html):", cleaned):
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _resolved_image_sources(mw: Any, sources: Iterable[str]) -> List[str]:
    media_dir = _collection_media_dir(mw)
    resolved: List[str] = []
    for source in sources:
        if re.match(r"(?i)^(?:https?|file):", source):
            resolved.append(source)
            continue
        if media_dir is None:
            resolved.append(source)
            continue
        try:
            path = (media_dir / source).resolve()
            path.relative_to(media_dir)
        except Exception:
            continue
        resolved.append(path.as_uri())
    return resolved


def _collection_media_dir(mw: Any):
    try:
        from pathlib import Path

        return Path(mw.col.media.dir()).resolve()
    except Exception:
        return None


def _note_field_names(note: Any) -> List[str]:
    try:
        return [str(key) for key in note.keys()]
    except Exception:
        return []


def note_field_names(note: Any) -> List[str]:
    return _note_field_names(note)


def _note_type_name(note: Any) -> str:
    try:
        return str(note.note_type().get("name", ""))
    except Exception:
        try:
            return str(note.model().get("name", ""))
        except Exception:
            return ""


def card_question_contains_target_field(card: Any, note: Any, target_field: str) -> bool:
    return _card_question_contains_field(card, note, target_field)


def card_review_direction(
    card: Any, note: Any, config: ContextConfig
) -> Tuple[str, bool]:
    """Return the configured review direction and whether the template is eligible."""
    return _card_review_direction(card, note, config)


def card_template_labels(card: Any, note: Any) -> List[str]:
    return _card_template_labels(card, note)


def card_template_name(card: Any, note: Any) -> str:
    template = _card_template(card, note)
    if not template:
        return "Card %s" % (_card_ordinal(card) + 1)
    return str(template.get("name", "") or "").strip() or "Card %s" % (
        _card_ordinal(card) + 1
    )


def card_question_field_names(card: Any, note: Any) -> Set[str]:
    template = _card_template(card, note)
    if not template:
        return set()
    return visible_question_field_names(str(template.get("qfmt", "") or ""))


def card_question_format(card: Any, note: Any) -> str:
    template = _card_template(card, note)
    return str(template.get("qfmt", "") or "") if template else ""


def _card_template_allowed(card: Any, note: Any, included_templates: Sequence[str]) -> bool:
    allowed = {_template_label_key(item) for item in included_templates if str(item).strip()}
    if not allowed:
        return True
    labels = {_template_label_key(item) for item in _card_template_labels(card, note)}
    return bool(labels.intersection(allowed))


def _card_review_direction(
    card: Any, note: Any, config: ContextConfig
) -> Tuple[str, bool]:
    """Classify an eligible card while preserving the legacy template allow-list."""
    recognition_templates = getattr(config, "included_card_templates", ()) or ()
    recall_templates = getattr(config, "recall_templates", ()) or ()
    recognition_match = _card_template_matches(card, note, recognition_templates)
    recall_match = _card_template_matches(card, note, recall_templates)

    if recognition_match and recall_match:
        if _card_question_contains_field(card, note, config.target_field):
            return "recognition", True
        if _card_question_contains_native_field(card, note, config):
            return "recall", True
        return "recall", False
    if recall_match:
        # Recall templates are an independent allow-list, so a reverse card can
        # be enabled without also adding it to the legacy recognition list.
        return "recall", _card_question_contains_native_field(card, note, config)
    if recall_templates and not recognition_templates:
        # Once a profile explicitly enables recall routing, an empty
        # recognition list means recall-only. Legacy profiles (which have no
        # recall list) retain the historical empty-means-all behavior.
        return "recognition", False
    return "recognition", _card_template_allowed(card, note, recognition_templates)


def _card_template_matches(
    card: Any, note: Any, included_templates: Sequence[str]
) -> bool:
    allowed = {_template_label_key(item) for item in included_templates if str(item).strip()}
    if not allowed:
        return False
    labels = {_template_label_key(item) for item in _card_template_labels(card, note)}
    return bool(labels.intersection(allowed))


def _card_question_contains_native_field(
    card: Any, note: Any, config: ContextConfig
) -> bool:
    fields = {_field_name_key(field) for field in card_question_field_names(card, note)}
    target = _field_name_key(config.target_field)
    candidates = {
        _field_name_key(getattr(config, "dictionary_field", "")),
        *(
            _field_name_key(getattr(spec, "field", ""))
            for spec in (getattr(config, "solution_fields", ()) or ())
        ),
        *(
            _field_name_key(field)
            for field in (
                "Back",
                "Definition",
                "Meaning",
                "Translation",
                "English",
                "Native",
                "Answer",
            )
        ),
    }
    candidates.discard("")
    candidates.discard(target)
    return bool(fields.intersection(candidates))


def _normalized_direction(direction: Any) -> str:
    return "recall" if str(direction or "").strip().casefold() == "recall" else "recognition"


def _card_template_labels(card: Any, note: Any) -> List[str]:
    ordinal = _card_ordinal(card)
    labels = [str(ordinal + 1), "card:%s" % (ordinal + 1), "Card %s" % (ordinal + 1)]
    template = _card_template(card, note)
    if template:
        name = str(template.get("name", "") or "").strip()
        if name:
            labels.append(name)
    return labels


def _card_question_contains_field(card: Any, note: Any, target_field: str) -> bool:
    target = str(target_field or "").strip()
    if not target:
        return True
    template = _card_template(card, note)
    if not template:
        return False
    qfmt = str(template.get("qfmt", "") or "")
    if not qfmt.strip():
        return False
    fields = visible_question_field_names(qfmt)
    if not fields:
        return False
    normalized_target = _field_name_key(target)
    return normalized_target in {_field_name_key(field) for field in fields}


def _card_template(card: Any, note: Any) -> Optional[Dict[str, Any]]:
    template_method = getattr(card, "template", None)
    if callable(template_method):
        try:
            template = template_method()
            if isinstance(template, dict):
                return template
        except Exception:
            pass

    model = None
    for method_name in ("model", "note_type"):
        method = getattr(note, method_name, None)
        if callable(method):
            try:
                model = method()
                if model:
                    break
            except Exception:
                pass
    if not isinstance(model, dict):
        return None
    templates = model.get("tmpls") or []
    if not isinstance(templates, list) or not templates:
        return None

    ordinal = _card_ordinal(card)
    if ordinal < 0 or ordinal >= len(templates):
        return None
    template = templates[ordinal]
    return template if isinstance(template, dict) else None


def _card_ordinal(card: Any) -> int:
    for attr in ("ord", "template_idx", "template_index"):
        try:
            value = getattr(card, attr, None)
            if value is not None:
                return int(value)
        except Exception:
            pass
    return 0


def _field_name_key(field_name: str) -> str:
    return re.sub(r"\s+", " ", str(field_name or "").strip()).casefold()


def _template_label_key(label: str) -> str:
    return re.sub(r"\s+", " ", str(label or "").strip()).casefold()


def _card_allowed(card: Any, config: ContextConfig) -> bool:
    queue = _card_queue(card)
    card_type = _card_type(card)
    if not config.include_new_cards and (queue == 0 or card_type == 0):
        return False
    if not config.include_learning_cards and (queue in (1, 3) or card_type in (1, 3)):
        return False
    return True


def _card_is_new(card: Any) -> bool:
    return _card_queue(card) == 0 or _card_type(card) == 0


def _card_is_learning(card: Any) -> bool:
    return _card_queue(card) in (1, 3) or _card_type(card) in (1, 3)


def _intraday_learning_step_is_early(card: Any, now: int) -> bool:
    return _card_queue(card) == 1 and _int_attr(card, "due", 0) > int(now)


def _card_is_in_filtered_deck(mw: Any, card_id: Any, card: Any) -> bool:
    if _int_attr(card, "odid", 0) != 0:
        return True
    db = _collection_db(mw)
    if db is None:
        return False
    try:
        row = _db_first(db, "SELECT odid FROM cards WHERE id = ?", (_safe_card_id(card_id) or card_id,))
        if row is None:
            return False
        if hasattr(row, "keys"):
            odid = row["odid"]
        elif isinstance(row, dict):
            odid = row.get("odid")
        else:
            odid = row[0]
        return int(odid or 0) != 0
    except Exception:
        return False


def _card_queue(card: Any) -> int:
    return _int_attr(card, "queue", 0)


def _card_type(card: Any) -> int:
    return _int_attr(card, "type", 0)


def _due_metrics(card: Any, today: int) -> tuple[float, int, float]:
    try:
        due = _int_attr(card, "due", 0)
        queue = _card_queue(card)
        card_type = _card_type(card)
    except Exception:
        return 0.0, 0, 10.0

    if queue in (2, 3) or card_type == 2:
        due_in_days = due - today
        overdue = float(max(0, -due_in_days))
        if due_in_days <= 0:
            return overdue, due_in_days, 10.0 + min(overdue, 30.0) / 3.0
        return 0.0, due_in_days, max(0.5, 6.0 / float(due_in_days + 1))
    return 0.0, 0, 10.0


def _due_card_sort_key(card: DueCard) -> tuple[float, int, int, str]:
    return (-float(card.priority or 0.0), int(card.due_in_days), int(card.card_id), card.match_key)


def _card_in_review_window(card: Any, today: int, future_due_days: int) -> bool:
    if future_due_days <= 0:
        return True
    queue = _card_queue(card)
    card_type = _card_type(card)
    if queue in (2, 3) or card_type == 2:
        due = _int_attr(card, "due", today)
        return due <= today + future_due_days
    return True


def _unique_ids(card_ids: Iterable[Any]) -> List[int]:
    seen: Set[int] = set()
    unique: List[int] = []
    for card_id in card_ids:
        try:
            parsed = int(card_id)
        except Exception:
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        unique.append(parsed)
    return unique


def _safe_card_id(card_id: Any) -> Optional[int]:
    try:
        return int(card_id)
    except Exception:
        return None


def _int_attr(obj: Any, attr: str, default: int) -> int:
    try:
        return int(getattr(obj, attr, default) or default)
    except Exception:
        return default


def _strip_html(value: str) -> str:
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()
