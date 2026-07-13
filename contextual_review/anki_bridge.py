"""Small Anki API adapter used by the contextual reviewer."""

from __future__ import annotations

import html
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .config import ContextConfig
from .debug_log import append_debug_log
from .normalizer import (
    matching_key_for_word,
    normalize_form,
    normalize_word,
    select_target_tokens,
)
from .types import DueCard, ReviewTask, SolutionFieldValue

Answerer = Callable[[Any, int], None]


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
    undo_snapshot: Optional["BatchUndoSnapshot"] = None


@dataclass(frozen=True)
class BatchUndoSnapshot:
    card_rows: Dict[int, Dict[str, Any]]
    revlog_ids: List[int]


class CardAnswerError(RuntimeError):
    def __init__(self, message: str, answered_card_ids: Optional[List[int]] = None) -> None:
        super().__init__(message)
        self.answered_card_ids = answered_card_ids or []


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

    return _scope_query(mw, config, query)


def build_future_search_query(mw: Any, config: ContextConfig) -> str:
    extra_filter = _custom_filter_without_due(config.custom_search_query)
    query = "prop:due<=%s" % int(config.future_due_days)
    if extra_filter:
        query = "%s %s" % (query, extra_filter)
    if not config.include_new_cards:
        query = "(%s) -is:new" % query
    if not config.include_learning_cards:
        query = "(%s) -is:learn" % query
    return _scope_query(mw, config, query)


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
        if not _card_in_review_window(card, today, config.future_due_days):
            _increment_skip(skipped, "future_window")
            continue

        note_type = _note_type_name(note)
        if note_type_filter and note_type not in note_type_filter:
            _increment_skip(skipped, "note_type")
            continue
        if not _card_template_allowed(card, note, config.included_card_templates):
            _increment_skip(skipped, "card_template")
            continue

        field_value = _field_value(note, config.target_field)
        if not field_value:
            _increment_skip(skipped, "target_field")
            continue
        solution_fields = _solution_field_values(mw, note, config)
        plain_definition = _first_text_solution(solution_fields)
        if not plain_definition:
            definition_value = _definition_value(note, config)
            plain_definition = html.unescape(_strip_html(definition_value)) if definition_value else ""
        if config.require_target_on_question and not _card_question_contains_field(
            card,
            note,
            config.target_field,
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
        target_display = _target_display_text(plain_value)
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
                )
            )

    sorted_due_cards = sorted(due_cards, key=_due_card_sort_key)
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
        return AnswerSummary([], [], [])

    answer_card_ids = [answer.card_id for answer in answers]
    append_debug_log(
        "answer_review_task_start",
        sentence_id=task.sentence_id,
        unknown_keys=unknown_key_list,
        unknown_card_ids=unknown_card_id_list,
        answers=_debug_answer_plan(answers),
        before=_debug_card_states(mw, answer_card_ids),
    )

    native_error: Optional[Exception] = None
    try:
        summary = _answer_with_anki_scheduler(mw, answers)
        append_debug_log(
            "answer_review_task_success",
            scheduler="native",
            sentence_id=task.sentence_id,
            summary=_debug_answer_summary(summary),
            after=_debug_card_states(mw, answer_card_ids),
        )
        return summary
    except CardAnswerError as exc:
        if exc.answered_card_ids:
            append_debug_log(
                "answer_review_task_error",
                scheduler="native",
                sentence_id=task.sentence_id,
                error=str(exc),
                answered_card_ids=exc.answered_card_ids,
                after=_debug_card_states(mw, answer_card_ids),
            )
            raise
        native_error = exc
    except Exception as exc:
        native_error = exc

    manual_summary = _answer_with_contextual_scheduler(mw, answers)
    if manual_summary is not None:
        append_debug_log(
            "answer_review_task_success",
            scheduler="contextual_fallback",
            sentence_id=task.sentence_id,
            native_error=str(native_error) if native_error is not None else "",
            summary=_debug_answer_summary(manual_summary),
            after=_debug_card_states(mw, answer_card_ids),
        )
        return manual_summary

    if native_error is not None:
        append_debug_log(
            "answer_review_task_error",
            scheduler="unavailable",
            sentence_id=task.sentence_id,
            error=str(native_error),
            after=_debug_card_states(mw, answer_card_ids),
        )
        raise native_error

    append_debug_log(
        "answer_review_task_error",
        scheduler="unavailable",
        sentence_id=task.sentence_id,
        error="No compatible Anki scheduler was available.",
        after=_debug_card_states(mw, answer_card_ids),
    )
    raise RuntimeError("No compatible Anki scheduler was available.")


def _answer_with_anki_scheduler(mw: Any, answers: Sequence[CardAnswer]) -> AnswerSummary:
    answerer = _scheduler_answerer(mw)
    cards = _load_cards_for_answers(mw, answers)

    _checkpoint(mw, "Contextual Review")

    answered_card_ids: List[int] = []
    try:
        for answer in answers:
            card = cards[answer.card_id]
            _prepare_card_timer(card)
            answerer(card, answer.ease)
            answered_card_ids.append(answer.card_id)
    except Exception as exc:
        if answered_card_ids:
            _flush_collection(mw)
        raise CardAnswerError(
            "Could not answer card %s after answering %s card(s): %s"
            % (answers[len(answered_card_ids)].card_id, len(answered_card_ids), exc),
            answered_card_ids,
        ) from exc

    _flush_collection(mw)
    return AnswerSummary(
        answered_card_ids=answered_card_ids,
        unknown_card_ids=[answer.card_id for answer in answers if answer.is_unknown],
        known_card_ids=[answer.card_id for answer in answers if not answer.is_unknown],
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


def restore_answer_snapshot(mw: Any, snapshot: Optional[BatchUndoSnapshot]) -> None:
    if snapshot is None:
        return
    if _collection_db(mw) is None:
        raise RuntimeError("Cannot restore contextual review: collection database is unavailable.")
    _restore_snapshot_rows(mw, snapshot)


def _answer_with_contextual_scheduler(
    mw: Any, answers: Sequence[CardAnswer]
) -> Optional[AnswerSummary]:
    db = _collection_db(mw)
    if db is None:
        return None

    card_ids = [answer.card_id for answer in answers]
    card_rows = _read_card_rows(db, card_ids)
    missing = [card_id for card_id in card_ids if card_id not in card_rows]
    if missing:
        raise RuntimeError("Could not load card row(s): %s" % ", ".join(str(card_id) for card_id in missing))
    filtered = [card_id for card_id, row in card_rows.items() if int(row.get("odid") or 0)]
    if filtered:
        raise RuntimeError(
            "Contextual Review cannot manually schedule filtered-deck card(s): %s. "
            "Empty or rebuild the filtered deck, then review the source deck."
            % ", ".join(str(card_id) for card_id in sorted(filtered))
        )

    snapshot = BatchUndoSnapshot(
        card_rows={card_id: dict(card_rows[card_id]) for card_id in card_ids},
        revlog_ids=[],
    )
    now = int(time.time())
    today = int(getattr(getattr(mw.col, "sched", None), "today", 0) or 0)
    usn = _collection_usn(mw)

    try:
        for index, answer in enumerate(answers):
            old_row = card_rows[answer.card_id]
            revlog_id = _next_revlog_id(db, now, index)
            new_row, revlog_row = _scheduled_card_update(old_row, answer, today, now, usn, revlog_id)
            _write_card_row(db, new_row)
            _insert_revlog_row(db, revlog_row)
            snapshot.revlog_ids.append(int(revlog_row["id"]))

        _commit_collection(mw)
        _flush_collection(mw)
    except Exception as exc:
        _restore_snapshot_rows(mw, snapshot)
        raise RuntimeError("Contextual scheduler failed and restored the previous card state: %s" % exc) from exc
    return AnswerSummary(
        answered_card_ids=[answer.card_id for answer in answers],
        unknown_card_ids=[answer.card_id for answer in answers if answer.is_unknown],
        known_card_ids=[answer.card_id for answer in answers if not answer.is_unknown],
        undo_snapshot=snapshot,
)


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
        "has_undo_snapshot": summary.undo_snapshot is not None,
    }


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


def _restore_snapshot_rows(mw: Any, snapshot: BatchUndoSnapshot) -> None:
    db = _collection_db(mw)
    if db is None:
        return
    for revlog_id in snapshot.revlog_ids:
        _db_execute(db, "DELETE FROM revlog WHERE id = ?", (revlog_id,))
    for row in snapshot.card_rows.values():
        _write_card_row(db, row)
    _commit_collection(mw)
    _flush_collection(mw)


def _scheduled_card_update(
    old_row: Dict[str, Any],
    answer: CardAnswer,
    today: int,
    now: int,
    usn: int,
    revlog_id: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    old_type = int(old_row.get("type") or 0)
    old_queue = int(old_row.get("queue") or 0)
    old_ivl = int(old_row.get("ivl") or 0)
    old_factor = int(old_row.get("factor") or 2500)
    old_lapses = int(old_row.get("lapses") or 0)
    old_reps = int(old_row.get("reps") or 0)

    new_row = dict(old_row)
    new_row["mod"] = now
    new_row["usn"] = usn
    new_row["reps"] = old_reps + 1

    if answer.is_unknown:
        new_factor = max(1300, old_factor - 200)
        new_ivl = 0
        new_due = now
        new_lapses = old_lapses + (1 if old_type == 2 or old_queue == 2 else 0)
        revlog_type = 2 if old_type == 2 or old_queue == 2 else 0
        new_type = 3 if old_type == 2 or old_queue == 2 else 1
        new_queue = 1
        new_left = 1001
    else:
        new_factor = old_factor
        base_ivl = max(1, old_ivl)
        growth = max(1, round(base_ivl * max(1.3, old_factor / 1000.0)))
        new_ivl = max(base_ivl + 1, growth)
        new_due = today + new_ivl
        new_lapses = old_lapses
        revlog_type = 1 if old_type == 2 or old_queue == 2 else 0
        new_type = 2
        new_queue = 2
        new_left = 0

    new_row["type"] = new_type
    new_row["queue"] = new_queue
    new_row["due"] = new_due
    new_row["ivl"] = new_ivl
    new_row["factor"] = new_factor
    new_row["lapses"] = new_lapses
    new_row["left"] = new_left
    new_row["odue"] = 0
    new_row["odid"] = 0

    return new_row, {
        "id": revlog_id,
        "cid": int(answer.card_id),
        "usn": usn,
        "ease": int(answer.ease),
        "ivl": int(new_ivl),
        "lastIvl": int(old_ivl),
        "factor": int(new_factor),
        "time": 0,
        "type": revlog_type,
    }


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


def _collection_usn(mw: Any) -> int:
    usn = getattr(getattr(mw, "col", None), "usn", None)
    if callable(usn):
        try:
            return int(usn())
        except Exception:
            pass
    return -1


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


def _write_card_row(db: Any, row: Dict[str, Any]) -> None:
    assignments = ", ".join("%s = ?" % column for column in CARD_COLUMNS if column != "id")
    params = tuple(row[column] for column in CARD_COLUMNS if column != "id") + (row["id"],)
    _db_execute(db, "UPDATE cards SET %s WHERE id = ?" % assignments, params)


def _insert_revlog_row(db: Any, row: Dict[str, Any]) -> None:
    columns = ("id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type")
    placeholders = ", ".join("?" for _ in columns)
    _db_execute(
        db,
        "INSERT INTO revlog(%s) VALUES (%s)" % (", ".join(columns), placeholders),
        tuple(row[column] for column in columns),
    )


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


def _db_execute(db: Any, sql: str, params: Sequence[Any] = ()) -> Any:
    try:
        return db.execute(sql, *params)
    except (TypeError, ValueError):
        return db.execute(sql, tuple(params))


def _commit_collection(mw: Any) -> None:
    col = getattr(mw, "col", None)
    save = getattr(col, "save", None)
    if callable(save):
        try:
            save()
            return
        except Exception:
            pass
    commit = getattr(_collection_db(mw), "commit", None)
    if callable(commit):
        commit()


def _next_revlog_id(db: Any, now: int, offset: int) -> int:
    revlog_id = now * 1000 + offset
    while _db_first(db, "SELECT id FROM revlog WHERE id = ?", (revlog_id,)) is not None:
        revlog_id += 1
    return revlog_id


def _scheduler_answerer(mw: Any) -> Answerer:
    scheduler = mw.col.sched
    if hasattr(scheduler, "answerCard"):
        return scheduler.answerCard
    if hasattr(scheduler, "answer_card"):
        return scheduler.answer_card
    raise RuntimeError("This Anki scheduler does not expose answerCard().")


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


def _checkpoint(mw: Any, name: str) -> None:
    checkpoint = getattr(mw, "checkpoint", None)
    if callable(checkpoint):
        checkpoint(name)
        return
    raise RuntimeError("This Anki build does not expose mw.checkpoint().")


def _prepare_card_timer(card: Any) -> None:
    for method_name in ("start_timer", "startTimer"):
        method = getattr(card, method_name, None)
        if callable(method):
            try:
                method()
                return
            except Exception:
                pass

    now = time.time()
    for attr in ("timer_started", "timerStarted"):
        try:
            if getattr(card, attr, None) is None:
                setattr(card, attr, now)
        except Exception:
            pass


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
        if not key or key in checked:
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


def _first_text_solution(values: Sequence[SolutionFieldValue]) -> str:
    for value in values:
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
    return _template_field_names(str(template.get("qfmt", "") or ""))


def card_question_format(card: Any, note: Any) -> str:
    template = _card_template(card, note)
    return str(template.get("qfmt", "") or "") if template else ""


def _card_template_allowed(card: Any, note: Any, included_templates: Sequence[str]) -> bool:
    allowed = {_template_label_key(item) for item in included_templates if str(item).strip()}
    if not allowed:
        return True
    labels = {_template_label_key(item) for item in _card_template_labels(card, note)}
    return bool(labels.intersection(allowed))


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
    fields = _template_field_names(qfmt)
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


def _template_field_names(qfmt: str) -> Set[str]:
    names: Set[str] = set()
    for match in re.finditer(r"{{\s*([^{}]+?)\s*}}", qfmt):
        expression = match.group(1).strip()
        field_name = _field_name_from_template_expression(expression)
        if field_name:
            names.add(field_name)
    return names


def _field_name_from_template_expression(expression: str) -> str:
    expression = str(expression or "").strip()
    if not expression:
        return ""
    if expression[0] in "#/^":
        expression = expression[1:].strip()
    elif expression.startswith("/"):
        expression = expression[1:].strip()
    if ":" in expression:
        expression = expression.rsplit(":", 1)[-1].strip()
    if not expression or expression in {"FrontSide", "Tags", "Deck", "Subdeck", "Card"}:
        return ""
    return expression


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
