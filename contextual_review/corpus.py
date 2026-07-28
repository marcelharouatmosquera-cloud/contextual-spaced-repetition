"""SQLite FTS5 corpus access and ranking."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from .language_profiles import language_match_codes
from .normalizer import (
    contains_unsegmented_script,
    count_words,
    is_unsegmented_language,
    matching_key_for_word,
    normalize_form,
    split_text_tokens,
)
from .types import DueCard, ReviewTask, SentenceCandidate, TargetWordDefinition, Token

SCHEMA = """
CREATE TABLE IF NOT EXISTS sentences (
  id INTEGER PRIMARY KEY,
  language TEXT NOT NULL,
  full_text TEXT NOT NULL,
  translation TEXT,
  word_count INTEGER DEFAULT 0,
  source TEXT,
  quality_flags TEXT DEFAULT "",
  UNIQUE(language, full_text)
);

CREATE VIRTUAL TABLE IF NOT EXISTS sentence_forms
USING FTS5(sentence_id UNINDEXED, word_form_list);

CREATE TABLE IF NOT EXISTS word_forms (
  form TEXT,
  base TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_word_forms_form_base ON word_forms(form, base);
CREATE INDEX IF NOT EXISTS idx_word_forms_form ON word_forms(form);
CREATE INDEX IF NOT EXISTS idx_word_forms_base ON word_forms(base);

CREATE TABLE IF NOT EXISTS sentence_ngrams (
  ngram TEXT NOT NULL,
  sentence_id INTEGER NOT NULL,
  PRIMARY KEY(ngram, sentence_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_sentence_ngrams_sentence ON sentence_ngrams(sentence_id);

CREATE TABLE IF NOT EXISTS corpus_meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

CJK_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS fts_cjk
USING FTS5(text, tokenize='trigram');
"""

WORD_FORMS_BACKFILL_KEY = "word_forms_backfill_v1"
SENTENCE_FORMS_BACKFILL_KEY = "sentence_forms_backfill_v1"
SENTENCE_NGRAMS_BACKFILL_KEY = "sentence_ngrams_backfill_v2"
CJK_FTS_BACKFILL_KEY = "fts_cjk_backfill_v1"
REVIEW_QUERY_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class QueryExpansion:
    base_key: str
    forms: FrozenSet[str]
    wildcard_prefix: str = ""


def connect_database(path: Path) -> sqlite3.Connection:
    """Open a writable corpus and apply schema/import migrations.

    Review selection deliberately uses :func:`open_review_database` instead so
    clicking Start Review can never trigger schema writes or legacy backfills.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        ensure_database_schema(conn)
        # Schema/index repairs are part of opening the corpus, not the caller's
        # later import transaction. Persist them so review does not redo the
        # same repair on every connection.
        conn.commit()
    except Exception:
        conn.close()
        raise
    return conn


def open_review_database(path: Path) -> sqlite3.Connection:
    """Open an existing corpus read-only, without running migrations."""
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError("Sentence database does not exist: %s" % resolved)
    conn = sqlite3.connect(
        "%s?mode=ro" % resolved.as_uri(),
        uri=True,
        timeout=2,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    deadline = time.monotonic() + REVIEW_QUERY_TIMEOUT_SECONDS
    conn.set_progress_handler(
        lambda: 1 if time.monotonic() >= deadline else 0,
        10_000,
    )
    return conn


def initialize_database(path: Path) -> None:
    conn = connect_database(path)
    try:
        conn.commit()
    finally:
        conn.close()


def migrate_database(path: Path) -> None:
    """Apply corpus schema migrations to an existing writable database."""
    conn = connect_database(path)
    conn.close()


def sentence_count_for_language(path: Path, language: str) -> int:
    """Return the number of stored sentences matching a language profile."""
    resolved = Path(path)
    if not resolved.is_file():
        return 0
    codes = language_match_codes(language)
    placeholders = ",".join("?" for _code in codes)
    conn = open_review_database(resolved)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM sentences WHERE language IN (%s)" % placeholders,
            tuple(codes),
        ).fetchone()
        return int(row[0] if row else 0)
    finally:
        conn.close()


def delete_sentences_for_language(path: Path, language: str, limit: int = 0) -> int:
    """Delete newest sentences for one language, or all when limit is zero."""
    resolved = Path(path)
    if not resolved.is_file():
        return 0
    codes = language_match_codes(language)
    placeholders = ",".join("?" for _code in codes)
    conn = connect_database(resolved)
    try:
        query = "SELECT id FROM sentences WHERE language IN (%s) ORDER BY id DESC" % placeholders
        parameters: Tuple[Any, ...] = tuple(codes)
        requested = max(0, int(limit or 0))
        if requested:
            query += " LIMIT ?"
            parameters += (requested,)
        sentence_ids = [int(row[0]) for row in conn.execute(query, parameters)]
        if not sentence_ids:
            return 0
        for offset in range(0, len(sentence_ids), 400):
            batch = sentence_ids[offset : offset + 400]
            marks = ",".join("?" for _sentence_id in batch)
            conn.execute(
                "DELETE FROM sentence_forms WHERE sentence_id IN (%s)" % marks,
                tuple(batch),
            )
            conn.execute(
                "DELETE FROM sentence_ngrams WHERE sentence_id IN (%s)" % marks,
                tuple(batch),
            )
            if _table_exists(conn, "fts_cjk"):
                conn.execute(
                    "DELETE FROM fts_cjk WHERE rowid IN (%s)" % marks,
                    tuple(batch),
                )
            conn.execute("DELETE FROM sentences WHERE id IN (%s)" % marks, tuple(batch))
        conn.commit()
        return len(sentence_ids)
    finally:
        conn.close()


def ensure_database_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cjk_fts_available = _ensure_cjk_fts_schema(conn)
    sentence_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(sentences)").fetchall()
    }
    for name, definition in (
        ("translation", "TEXT"),
        ("word_count", "INTEGER DEFAULT 0"),
        ("source", "TEXT"),
        ("quality_flags", 'TEXT DEFAULT ""'),
    ):
        if name not in sentence_columns:
            conn.execute("ALTER TABLE sentences ADD COLUMN %s %s" % (name, definition))
    _backfill_word_forms_from_word_map(conn)
    _backfill_sentence_forms(conn)
    _backfill_sentence_ngrams(conn)
    if cjk_fts_available:
        _backfill_cjk_fts(conn)


def insert_sentence(
    conn: sqlite3.Connection,
    language: str,
    full_text: str,
    translation: Optional[str],
    word_map: Optional[Dict[str, str]] = None,
    source: str = "",
    word_count: int = 0,
    quality_flags: str = "",
    return_existing: bool = True,
) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO sentences(language, full_text, translation, word_count, source, quality_flags)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            language,
            full_text,
            translation,
            int(word_count or count_words(full_text, language)),
            source,
            quality_flags,
        ),
    )
    if cur.rowcount == 0:
        if not return_existing:
            return 0
        row = conn.execute(
            "SELECT id FROM sentences WHERE language = ? AND full_text = ?",
            (language, full_text),
        ).fetchone()
        return _row_value(row, "id") if row else 0

    sentence_id = int(cur.lastrowid)
    forms = _word_forms(word_map, full_text)
    conn.execute(
        "INSERT INTO sentence_forms(sentence_id, word_form_list) VALUES (?, ?)",
        (sentence_id, " ".join(forms)),
    )
    _insert_sentence_ngrams(conn, sentence_id, full_text)
    _insert_cjk_fts(conn, sentence_id, full_text)
    if word_map:
        upsert_word_forms(conn, word_map)
    return sentence_id


def upsert_word_forms(conn: sqlite3.Connection, word_forms) -> None:
    items = word_forms.items() if isinstance(word_forms, dict) else word_forms
    rows = []
    seen: Set[Tuple[str, str]] = set()
    for form, base in items:
        if not form or not base:
            continue
        row = (str(form), str(base))
        if row in seen:
            continue
        seen.add(row)
        rows.append(row)
    if not rows:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO word_forms(form, base) VALUES (?, ?)",
        rows,
    )


def select_review_task(
    db_path: Path,
    due_cards: Sequence[DueCard],
    language: str,
    shown_sentence_ids: Set[int],
    candidate_limit: int,
    min_sentence_words: int = 2,
    max_sentence_words: int = 12,
    query_term_limit: int = 40,
    matching_mode: str = "exact_form",
    soft_avoid_sentence_ids: Optional[Set[int]] = None,
    _excluded_anchor_keys: Optional[Set[str]] = None,
) -> Optional[ReviewTask]:
    conn = open_review_database(db_path)
    try:
        due_by_key = _due_by_key(conn, due_cards, matching_mode)
        if not due_by_key:
            return None
        expansions = _query_expansions(conn, due_by_key, matching_mode)
        if not expansions:
            return None
        excluded_anchor_keys = set(_excluded_anchor_keys or ())
        anchor_key = _greedy_anchor_key(due_by_key, excluded_anchor_keys)
        if not anchor_key:
            return None
        anchor_expansions = [
            expansion for expansion in expansions if expansion.base_key == anchor_key
        ]
        if not anchor_expansions:
            return None

        rows = _candidate_rows(
            conn,
            due_by_key,
            anchor_expansions,
            language_match_codes(language),
            int(candidate_limit),
            int(query_term_limit),
            is_unsegmented_language(language),
        )
    except sqlite3.OperationalError as exc:
        if "interrupted" in str(exc).lower():
            raise TimeoutError(
                "Sentence search exceeded %s seconds. Run Diagnostics, reduce Max due cards, "
                "or use a smaller corpus." % int(REVIEW_QUERY_TIMEOUT_SECONDS)
            ) from exc
        raise
    finally:
        conn.close()

    candidates: List[SentenceCandidate] = []
    for row in rows:
        sentence_id = int(row["id"])
        if sentence_id in shown_sentence_ids:
            continue

        row_language = str(row["language"])
        word_count = int(row["word_count"] or 0) or count_words(
            str(row["full_text"]), row_language
        )
        if word_count < min_sentence_words or word_count > max_sentence_words:
            continue

        sentence_keys = _sentence_key_set(str(row["key_list"]))
        if is_unsegmented_language(row_language):
            matched = _matched_base_keys_in_text(str(row["full_text"]), expansions)
        else:
            matched = _matched_base_keys(sentence_keys, expansions)
        if not matched:
            continue
        score = _score_match(matched, due_by_key)
        candidates.append(
            SentenceCandidate(
                sentence_id=sentence_id,
                language=str(row["language"]),
                full_text=str(row["full_text"]),
                translation=row["translation"],
                matched_lemmas=matched,
                score=score,
                matched_card_count=_matched_card_count(matched, due_by_key),
                matched_learning_card_count=_matched_learning_card_count(matched, due_by_key),
                bm25_score=float(row["bm25_score"] or 0.0),
                word_count=word_count,
            )
        )

    if not candidates:
        remaining_anchor_keys = set(due_by_key) - excluded_anchor_keys - {anchor_key}
        if not remaining_anchor_keys:
            return None
        return select_review_task(
            db_path,
            due_cards,
            language,
            shown_sentence_ids,
            candidate_limit,
            min_sentence_words,
            max_sentence_words,
            query_term_limit,
            matching_mode,
            soft_avoid_sentence_ids,
            excluded_anchor_keys | {anchor_key},
        )

    soft_avoid = soft_avoid_sentence_ids or ()
    preferred = [candidate for candidate in candidates if candidate.sentence_id not in soft_avoid]
    best = min(preferred or candidates, key=_candidate_sort_key)
    card_ids_by_key: Dict[str, List[int]] = {}
    for lemma in best.matched_lemmas:
        card_ids_by_key[lemma] = sorted({card.card_id for card in due_by_key[lemma]})
    due_cards_by_id = _due_cards_by_id(best.matched_lemmas, due_by_key)
    tokens = _tokens_for_sentence(
        best.full_text,
        language,
        set(card_ids_by_key),
        matching_mode,
        card_ids_by_key,
        expansions,
        due_cards_by_id,
    )
    token_card_ids = {
        int(card_id)
        for token in tokens
        if token.is_target
        for card_id in token.card_ids
    }
    if token_card_ids:
        card_ids_by_key = {
            key: [card_id for card_id in card_ids if card_id in token_card_ids]
            for key, card_ids in card_ids_by_key.items()
        }
        card_ids_by_key = {
            key: card_ids for key, card_ids in card_ids_by_key.items() if card_ids
        }
    selected_due_by_key = {
        key: [card for card in due_by_key[key] if card.card_id in set(card_ids)]
        for key, card_ids in card_ids_by_key.items()
    }
    target_words = _target_words_for_match(tuple(card_ids_by_key), selected_due_by_key)

    return ReviewTask(
        sentence_id=best.sentence_id,
        language=best.language,
        full_text=best.full_text,
        translation=best.translation,
        tokens=tokens,
        card_ids_by_key=card_ids_by_key,
        target_words=target_words,
        matching_mode=matching_mode,
    )


def build_expanded_match_query(terms: Iterable[Tuple[str, bool]], limit: int = 40) -> str:
    pieces: List[str] = []
    for term, wildcard in terms:
        cleaned = normalize_form(term)
        if not cleaned:
            continue
        if wildcard:
            pieces.append("%s*" % cleaned)
        else:
            pieces.append('"%s"' % cleaned.replace('"', '""'))
    return " OR ".join(sorted(set(pieces))[:limit])


def _score_match(matched_lemmas: Sequence[str], due_by_lemma: Dict[str, List[DueCard]]) -> float:
    score = 0.0
    for lemma in matched_lemmas:
        for card in due_by_lemma.get(lemma, []):
            score += card.priority or (10.0 + min(float(card.overdue), 30.0) / 3.0)
    return score


def _greedy_anchor_key(
    due_by_key: Dict[str, List[DueCard]], excluded_keys: Optional[Set[str]] = None
) -> str:
    """Choose one most-urgent due word to anchor the next sentence query."""
    ranked = sorted(
        [
            (card, key)
            for key, cards in due_by_key.items()
            if key not in (excluded_keys or set())
            for card in cards
        ],
        key=lambda item: (
            -int(bool(item[0].is_learning_due)),
            -float(item[0].overdue or 0.0),
            -float(item[0].priority or 0.0),
            int(item[0].due_in_days),
            int(item[0].card_id),
            item[1],
        ),
    )
    return ranked[0][1] if ranked else ""


def _matched_card_count(matched_lemmas: Sequence[str], due_by_lemma: Dict[str, List[DueCard]]) -> int:
    card_ids: Set[int] = set()
    for lemma in matched_lemmas:
        card_ids.update(card.card_id for card in due_by_lemma.get(lemma, []))
    return len(card_ids)


def _matched_learning_card_count(
    matched_lemmas: Sequence[str], due_by_lemma: Dict[str, List[DueCard]]
) -> int:
    card_ids: Set[int] = set()
    for lemma in matched_lemmas:
        card_ids.update(
            card.card_id
            for card in due_by_lemma.get(lemma, [])
            if card.is_learning_due
        )
    return len(card_ids)


def _due_cards_by_id(
    matched_keys: Sequence[str], due_by_key: Dict[str, List[DueCard]]
) -> Dict[int, DueCard]:
    cards: Dict[int, DueCard] = {}
    for key in matched_keys:
        for card in due_by_key.get(key, ()):
            cards.setdefault(int(card.card_id), card)
    return cards


def _target_words_for_match(
    matched_keys: Sequence[str], due_by_key: Dict[str, List[DueCard]]
) -> Tuple[TargetWordDefinition, ...]:
    cards: List[DueCard] = []
    seen_card_ids: Set[int] = set()
    for key in matched_keys:
        for card in due_by_key.get(key, []):
            if card.card_id in seen_card_ids:
                continue
            seen_card_ids.add(card.card_id)
            cards.append(card)

    ordered = sorted(
        cards,
        key=lambda card: (
            -float(card.priority or 0.0),
            int(card.due_in_days),
            int(card.card_id),
            card.target_word.casefold(),
        ),
    )
    return tuple(
        TargetWordDefinition(
            card_id=card.card_id,
            target_word=card.target_word,
            definition=card.definition,
            solution_fields=card.solution_fields,
            good_interval=_good_interval_label(card),
            again_interval="today",
            direction=_due_card_direction(card),
        )
        for card in ordered
    )


def _good_interval_label(card: DueCard) -> str:
    base_interval = max(1, int(card.interval or 0))
    factor = max(1300, int(card.factor or 2500))
    growth = max(1, round(base_interval * max(1.3, factor / 1000.0)))
    days = max(base_interval + 1, growth)
    return _days_label(days)


def _days_label(days: int) -> str:
    days = max(0, int(days))
    if days <= 0:
        return "today"
    if days == 1:
        return "1 day"
    return "%s days" % days


def _candidate_sort_key(candidate: SentenceCandidate) -> Tuple[int, int, float, int, float, int, int]:
    return (
        -candidate.matched_card_count,
        -candidate.matched_learning_card_count,
        -candidate.score,
        0 if str(candidate.translation or "").strip() else 1,
        candidate.bm25_score,
        candidate.word_count,
        candidate.sentence_id,
    )


def _candidate_rows(
    conn: sqlite3.Connection,
    due_by_lemma: Dict[str, List[DueCard]],
    expansions: Sequence[QueryExpansion],
    languages: Sequence[str],
    candidate_limit: int,
    query_term_limit: int,
    include_substring_matches: bool = False,
) -> List[sqlite3.Row]:
    ranked_expansions = sorted(
        expansions,
        key=lambda expansion: (
            -sum(float(card.priority or 0.0) for card in due_by_lemma[expansion.base_key]),
            expansion.base_key,
        ),
    )
    if include_substring_matches:
        return _substring_candidate_rows(
            conn,
            ranked_expansions,
            languages,
            candidate_limit * 4,
        )
    seen_sentence_ids: Set[int] = set()
    rows: List[sqlite3.Row] = []
    chunk_size = max(1, min(query_term_limit, 40))
    ranked_terms: List[Tuple[str, bool]] = []
    for expansion in ranked_expansions:
        ranked_terms.extend((form, False) for form in expansion.forms)
        if expansion.wildcard_prefix:
            ranked_terms.append((expansion.wildcard_prefix, True))

    for index in range(0, len(ranked_terms), chunk_size):
        match_query = build_expanded_match_query(ranked_terms[index : index + chunk_size], chunk_size)
        if not match_query:
            continue
        chunk_rows = conn.execute(
            _candidate_sql("sentence_forms", "word_form_list", len(languages)),
            (match_query, *languages, max(candidate_limit * 2, 20)),
        ).fetchall()
        for row in chunk_rows:
            sentence_id = int(row["id"])
            if sentence_id in seen_sentence_ids:
                continue
            rows.append(row)
            seen_sentence_ids.add(sentence_id)
            if len(rows) >= candidate_limit * 4:
                return rows
    return rows


def _substring_candidate_rows(
    conn: sqlite3.Connection,
    expansions: Sequence[QueryExpansion],
    languages: Sequence[str],
    limit: int,
) -> List[sqlite3.Row]:
    forms: List[str] = []
    for expansion in expansions:
        for form in expansion.forms:
            cleaned = normalize_form(form)
            if cleaned and cleaned not in forms:
                forms.append(cleaned)
    if not forms:
        return []

    rows: List[sqlite3.Row] = []
    long_forms = [form for form in forms if len(form) >= 3]
    if long_forms and _table_exists(conn, "fts_cjk"):
        rows.extend(_fts_cjk_candidate_rows(conn, long_forms, languages, limit))

    seen_ids = {int(row["id"]) for row in rows}
    remaining_forms = [form for form in forms if len(form) < 3]
    if not rows and not _table_exists(conn, "fts_cjk"):
        remaining_forms = forms

    if remaining_forms and _table_exists(conn, "sentence_ngrams"):
        indexed_forms = [form for form in remaining_forms if len(form) >= 2]
        short_forms = [form for form in remaining_forms if len(form) < 2]
        indexed_rows = _indexed_substring_candidate_rows(
            conn,
            indexed_forms,
            languages,
            limit,
        )
        for row in indexed_rows:
            sentence_id = int(row["id"])
            if sentence_id not in seen_ids:
                seen_ids.add(sentence_id)
                rows.append(row)
        if short_forms and len(rows) < limit:
            for row in _scan_substring_candidate_rows(
                conn,
                short_forms,
                languages,
                limit,
            ):
                sentence_id = int(row["id"])
                if sentence_id in seen_ids:
                    continue
                seen_ids.add(sentence_id)
                rows.append(row)
        return rows[:limit]

    if remaining_forms and len(rows) < limit:
        for row in _scan_substring_candidate_rows(conn, remaining_forms, languages, limit):
            sentence_id = int(row["id"])
            if sentence_id not in seen_ids:
                seen_ids.add(sentence_id)
                rows.append(row)
    return rows[:limit]


def _fts_cjk_candidate_rows(
    conn: sqlite3.Connection,
    forms: Sequence[str],
    languages: Sequence[str],
    limit: int,
) -> List[sqlite3.Row]:
    """Retrieve unsegmented-text candidates from the FTS5 trigram index."""
    if not forms:
        return []
    language_placeholders = ", ".join("?" for _ in range(max(1, len(languages))))
    match_query = " OR ".join('"%s"' % form.replace('"', '""') for form in forms)
    sql = """
        SELECT s.id, s.language, s.full_text, s.translation, s.word_count,
               COALESCE(sf.word_form_list, '') AS key_list,
               bm25(fts_cjk) AS bm25_score,
               1 AS substring_match_count
        FROM fts_cjk
        JOIN sentences s ON s.id = fts_cjk.rowid
        LEFT JOIN sentence_forms sf ON sf.sentence_id = s.id
        WHERE fts_cjk MATCH ?
          AND s.language IN (%s)
        ORDER BY bm25_score, s.word_count, s.id
        LIMIT ?
    """ % language_placeholders
    return conn.execute(
        sql,
        (match_query, *languages, max(limit, 20)),
    ).fetchall()


def _indexed_substring_candidate_rows(
    conn: sqlite3.Connection,
    forms: Sequence[str],
    languages: Sequence[str],
    limit: int,
) -> List[sqlite3.Row]:
    if not forms:
        return []
    probes = _least_common_probe_ngrams(conn, forms)
    if not probes:
        return []
    probe_placeholders = ", ".join("?" for _ in probes)
    language_placeholders = ", ".join("?" for _ in range(max(1, len(languages))))
    predicates = " OR ".join("instr(lower(s.full_text), ?) > 0" for _ in forms)
    match_score = " + ".join(
        "CASE WHEN instr(lower(s.full_text), ?) > 0 THEN 1 ELSE 0 END" for _ in forms
    )
    sql = """
        SELECT s.id, s.language, s.full_text, s.translation, s.word_count,
               COALESCE(sf.word_form_list, '') AS key_list,
               -(%s) AS bm25_score,
               (%s) AS substring_match_count
        FROM (
            SELECT DISTINCT sentence_id
            FROM sentence_ngrams
            WHERE ngram IN (%s)
        ) candidates
        JOIN sentences s ON s.id = candidates.sentence_id
        LEFT JOIN sentence_forms sf ON sf.sentence_id = s.id
        WHERE s.language IN (%s)
          AND (%s)
        ORDER BY substring_match_count DESC, s.word_count, s.id
        LIMIT ?
    """ % (match_score, match_score, probe_placeholders, language_placeholders, predicates)
    return conn.execute(
        sql,
        (*forms, *forms, *probes, *languages, *forms, max(limit, 20)),
    ).fetchall()


def _least_common_probe_ngrams(
    conn: sqlite3.Connection, forms: Sequence[str]
) -> List[str]:
    grams_by_form = {form: _form_probe_ngrams(form) for form in forms}
    all_grams = sorted({gram for grams in grams_by_form.values() for gram in grams})
    if not all_grams:
        return []
    counts: Dict[str, int] = {}
    for offset in range(0, len(all_grams), 400):
        chunk = all_grams[offset : offset + 400]
        placeholders = ", ".join("?" for _ in chunk)
        counts.update(
            {
                str(row[0]): int(row[1])
                for row in conn.execute(
                    "SELECT ngram, COUNT(*) FROM sentence_ngrams "
                    "WHERE ngram IN (%s) GROUP BY ngram" % placeholders,
                    chunk,
                )
            }
        )
    return sorted(
        {
            min(grams, key=lambda gram: (counts.get(gram, 0), gram))
            for grams in grams_by_form.values()
            if grams
        }
    )


def _form_probe_ngrams(form: str) -> Tuple[str, ...]:
    width = 3 if len(form) >= 3 else 2
    return tuple(
        dict.fromkeys(
            form[index : index + width]
            for index in range(len(form) - width + 1)
        )
    )


def _scan_substring_candidate_rows(
    conn: sqlite3.Connection,
    forms: Sequence[str],
    languages: Sequence[str],
    limit: int,
) -> List[sqlite3.Row]:

    rows: List[sqlite3.Row] = []
    seen: Set[int] = set()
    language_placeholders = ", ".join("?" for _ in range(max(1, len(languages))))
    for index in range(0, len(forms), 30):
        chunk = forms[index : index + 30]
        predicates = " OR ".join("instr(s.full_text, ?) > 0" for _ in chunk)
        match_score = " + ".join(
            "CASE WHEN instr(s.full_text, ?) > 0 THEN 1 ELSE 0 END" for _ in chunk
        )
        sql = """
            SELECT s.id, s.language, s.full_text, s.translation, s.word_count,
                   COALESCE(sf.word_form_list, '') AS key_list,
                   -(%s) AS bm25_score,
                   (%s) AS substring_match_count
            FROM sentences s
            LEFT JOIN sentence_forms sf ON sf.sentence_id = s.id
            WHERE s.language IN (%s)
              AND (%s)
            ORDER BY substring_match_count DESC, s.word_count, s.id
            LIMIT ?
        """ % (match_score, match_score, language_placeholders, predicates)
        chunk_rows = conn.execute(
            sql,
            (*chunk, *chunk, *languages, *chunk, max(limit, 20)),
        ).fetchall()
        for row in chunk_rows:
            sentence_id = int(row["id"])
            if sentence_id in seen:
                continue
            seen.add(sentence_id)
            rows.append(row)
            if len(rows) >= limit:
                return rows
    return rows


def _candidate_sql(fts_table: str, fts_column: str, language_count: int) -> str:
    language_placeholders = ", ".join("?" for _ in range(max(1, language_count)))
    return """
        SELECT s.id, s.language, s.full_text, s.translation, s.word_count,
               sl.%s AS key_list,
               bm25(%s) AS bm25_score
        FROM %s sl
        JOIN sentences s ON s.id = sl.sentence_id
        WHERE %s MATCH ?
          AND s.language IN (%s)
        ORDER BY bm25_score
        LIMIT ?
        """ % (
        fts_column,
        fts_table,
        fts_table,
        fts_table,
        language_placeholders,
    )


def _due_by_key(
    conn: sqlite3.Connection, due_cards: Sequence[DueCard], matching_mode: str
) -> Dict[str, List[DueCard]]:
    due_by_lemma: Dict[str, List[DueCard]] = {}
    if matching_mode == "exact_form":
        for card in due_cards:
            key = card.match_key or card.word_form or normalize_form(card.target_word)
            if key:
                due_by_lemma.setdefault(key, []).append(card)
        return _prefer_recognition_for_mixed_keys(due_by_lemma)

    candidates_by_card: List[Tuple[DueCard, Tuple[str, ...]]] = []
    candidate_keys: Set[str] = set()
    for card in due_cards:
        candidates = tuple(
            dict.fromkeys(
                cleaned
                for value in (card.match_key, card.lemma, card.word_form, card.target_word)
                if (cleaned := normalize_form(str(value or "")))
            )
        )
        if not candidates:
            continue
        candidates_by_card.append((card, candidates))
        candidate_keys.update(candidates)

    resolved_bases = _resolve_word_form_bases(conn, candidate_keys)
    for card, candidates in candidates_by_card:
        key = next((resolved_bases[value] for value in candidates if value in resolved_bases), "")
        key = key or card.match_key or card.lemma
        if key:
            due_by_lemma.setdefault(key, []).append(card)
    return _prefer_recognition_for_mixed_keys(due_by_lemma)


def _prefer_recognition_for_mixed_keys(
    due_by_key: Dict[str, List[DueCard]]
) -> Dict[str, List[DueCard]]:
    """Never test recall and recognition through the same matched word key."""
    resolved: Dict[str, List[DueCard]] = {}
    for key, cards in due_by_key.items():
        directions = {_due_card_direction(card) for card in cards}
        if directions == {"recognition", "recall"}:
            resolved[key] = [
                card for card in cards if _due_card_direction(card) == "recognition"
            ]
        else:
            resolved[key] = list(cards)
    return resolved


def _due_card_direction(card: DueCard) -> str:
    return "recall" if str(card.direction or "").strip().casefold() == "recall" else "recognition"


def _resolve_word_form_bases(
    conn: sqlite3.Connection, candidate_keys: Set[str]
) -> Dict[str, str]:
    resolved: Dict[str, str] = {}
    ordered_keys = sorted(candidate_keys)
    for offset in range(0, len(ordered_keys), 400):
        chunk = ordered_keys[offset : offset + 400]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT form, base FROM word_forms "
            "WHERE form IN (%s) OR base IN (%s) "
            "ORDER BY CASE WHEN form = base THEN 0 ELSE 1 END"
            % (placeholders, placeholders),
            (*chunk, *chunk),
        ).fetchall()
        chunk_keys = set(chunk)
        for row in rows:
            form = normalize_form(str(row["form"]))
            base = normalize_form(str(row["base"]))
            if form in chunk_keys and base:
                resolved.setdefault(form, base)
            if base in chunk_keys:
                resolved.setdefault(base, base)
    return resolved


def _query_expansions(
    conn: sqlite3.Connection,
    due_by_key: Dict[str, List[DueCard]],
    matching_mode: str,
) -> List[QueryExpansion]:
    base_keys = sorted(
        {base_key for key in due_by_key if (base_key := normalize_form(key))}
    )
    if matching_mode == "exact_form":
        return [
            QueryExpansion(base_key=base_key, forms=frozenset((base_key,)))
            for base_key in base_keys
        ]

    requested_keys = set(base_keys)
    forms_by_base: Dict[str, Set[str]] = {}
    for offset in range(0, len(base_keys), 400):
        chunk = base_keys[offset : offset + 400]
        placeholders = ", ".join("?" for _ in chunk)
        rows = conn.execute(
            "SELECT form, base FROM word_forms "
            "WHERE base IN (%s) OR form IN (%s)" % (placeholders, placeholders),
            (*chunk, *chunk),
        ).fetchall()
        for row in rows:
            form = normalize_form(str(row["form"]))
            base = normalize_form(str(row["base"]))
            if base in requested_keys and form:
                forms_by_base.setdefault(base, {base}).add(form)
            if form in requested_keys:
                forms_by_base.setdefault(form, {form})

    return [
        QueryExpansion(
            base_key=base_key,
            forms=frozenset(forms_by_base.get(base_key, (base_key,))),
            wildcard_prefix="" if base_key in forms_by_base else base_key,
        )
        for base_key in base_keys
    ]


def _sentence_key_set(key_list: str) -> Set[str]:
    keys: Set[str] = set()
    for key in str(key_list or "").split():
        normalized = normalize_form(key)
        if normalized:
            keys.add(normalized)
    return keys


def _matched_base_keys(sentence_keys: Set[str], expansions: Sequence[QueryExpansion]) -> List[str]:
    matched: List[str] = []
    for expansion in expansions:
        if sentence_keys.intersection(expansion.forms):
            matched.append(expansion.base_key)
            continue
        if expansion.wildcard_prefix and any(
            key.startswith(expansion.wildcard_prefix) for key in sentence_keys
        ):
            matched.append(expansion.base_key)
    return sorted(set(matched))


def _matched_base_keys_in_text(
    full_text: str, expansions: Sequence[QueryExpansion]
) -> List[str]:
    normalized_text = normalize_form(full_text)
    matched: List[str] = []
    for expansion in expansions:
        if any(form and normalize_form(form) in normalized_text for form in expansion.forms):
            matched.append(expansion.base_key)
    return sorted(set(matched))


def _bases_for_form(form: str, expansions: Sequence[QueryExpansion]) -> List[str]:
    matched: List[str] = []
    for expansion in expansions:
        if form in expansion.forms:
            matched.append(expansion.base_key)
            continue
        if expansion.wildcard_prefix and form.startswith(expansion.wildcard_prefix):
            matched.append(expansion.base_key)
    return sorted(set(matched))


def _tokens_for_sentence(
    full_text: str,
    language: str,
    target_lemmas: Set[str],
    matching_mode: str,
    card_ids_by_key: Dict[str, List[int]],
    expansions: Sequence[QueryExpansion],
    due_cards_by_id: Dict[int, DueCard],
) -> List[Token]:
    if is_unsegmented_language(language):
        return _tokens_for_unsegmented_sentence(
            full_text,
            card_ids_by_key,
            expansions,
            due_cards_by_id,
        )
    tokens: List[Token] = []
    for token in split_text_tokens(full_text, language):
        if token.is_word:
            form = normalize_form(token.text)
            matched_bases = _bases_for_form(form, expansions)
            match_key = matched_bases[0] if matched_bases else matching_key_for_word(
                token.text,
                language,
                matching_mode,
            )
            candidate_card_ids = tuple(
                sorted(
                    {
                        int(card_id)
                        for base in matched_bases
                        for card_id in card_ids_by_key.get(base, [])
                    }
                )
            )
            card_ids, direction, hint = _token_target_metadata(
                candidate_card_ids,
                due_cards_by_id,
            )
            is_target = bool(card_ids) or (match_key in target_lemmas if match_key else False)
        else:
            match_key = ""
            card_ids = ()
            direction = "recognition"
            hint = ""
            is_target = False
        tokens.append(
            Token(
                text=token.text,
                lemma=token.lemma,
                is_word=token.is_word,
                is_target=is_target,
                match_key=match_key,
                lookup_text=normalize_form(token.text) if token.is_word else "",
                card_ids=card_ids,
                direction=direction,
                hint=hint,
            )
        )
    return tokens


def _tokens_for_unsegmented_sentence(
    full_text: str,
    card_ids_by_key: Dict[str, List[int]],
    expansions: Sequence[QueryExpansion],
    due_cards_by_id: Dict[int, DueCard],
) -> List[Token]:
    occurrences: List[Tuple[int, int, str, str]] = []
    for expansion in expansions:
        for form in sorted(expansion.forms, key=len, reverse=True):
            if not form:
                continue
            start = 0
            while True:
                index = full_text.find(form, start)
                if index < 0:
                    break
                occurrences.append((index, index + len(form), expansion.base_key, form))
                start = index + max(1, len(form))

    selected: List[Tuple[int, int, str, str]] = []
    occupied: Set[int] = set()
    for occurrence in sorted(occurrences, key=lambda item: (item[0], -(item[1] - item[0]))):
        start, end, _, _ = occurrence
        if any(position in occupied for position in range(start, end)):
            continue
        selected.append(occurrence)
        occupied.update(range(start, end))
    selected.sort(key=lambda item: item[0])

    tokens: List[Token] = []
    cursor = 0
    for start, end, base_key, form in selected:
        if start > cursor:
            tokens.append(Token(text=full_text[cursor:start], lemma="", is_word=False))
        candidate_card_ids = tuple(
            sorted({int(card_id) for card_id in card_ids_by_key.get(base_key, [])})
        )
        card_ids, direction, hint = _token_target_metadata(
            candidate_card_ids,
            due_cards_by_id,
        )
        tokens.append(
            Token(
                text=full_text[start:end],
                lemma=base_key,
                is_word=True,
                is_target=bool(card_ids),
                match_key=base_key,
                lookup_text=form,
                card_ids=card_ids,
                direction=direction,
                hint=hint,
            )
        )
        cursor = end
    if cursor < len(full_text):
        tokens.append(Token(text=full_text[cursor:], lemma="", is_word=False))
    if not tokens:
        return [Token(text=full_text, lemma="", is_word=False)]
    return tokens


def _token_target_metadata(
    card_ids: Sequence[int], due_cards_by_id: Dict[int, DueCard]
) -> Tuple[Tuple[int, ...], str, str]:
    cards = [due_cards_by_id[card_id] for card_id in card_ids if card_id in due_cards_by_id]
    directions = {_due_card_direction(card) for card in cards}
    if directions == {"recognition", "recall"}:
        # One DOM token cannot be both shown and blanked. Recognition wins and
        # the recall IDs are left due for the next freshly collected task.
        cards = [card for card in cards if _due_card_direction(card) == "recognition"]
        directions = {"recognition"}
    selected_card_ids = tuple(sorted({int(card.card_id) for card in cards}))
    direction = "recall" if directions == {"recall"} else "recognition"
    hints = tuple(
        dict.fromkeys(
            str(card.definition or "").strip()
            for card in cards
            if direction == "recall" and str(card.definition or "").strip()
        )
    )
    return selected_card_ids, direction, " / ".join(hints)


def _backfill_word_forms_from_word_map(conn: sqlite3.Connection) -> None:
    if _corpus_migration_completed(conn, WORD_FORMS_BACKFILL_KEY):
        return
    if not _table_exists(conn, "word_map"):
        _mark_corpus_migration_completed(conn, WORD_FORMS_BACKFILL_KEY)
        return
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO word_forms(form, base)
            SELECT word_form, lemma
            FROM word_map
            WHERE word_form IS NOT NULL AND word_form != ''
              AND lemma IS NOT NULL AND lemma != ''
            """
        )
        _mark_corpus_migration_completed(conn, WORD_FORMS_BACKFILL_KEY)
    except sqlite3.Error:
        return


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
    )


def _backfill_sentence_forms(conn: sqlite3.Connection) -> None:
    if _corpus_migration_completed(conn, SENTENCE_FORMS_BACKFILL_KEY):
        return
    try:
        missing_ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM sentences "
                "EXCEPT SELECT CAST(sentence_id AS INTEGER) FROM sentence_forms"
            )
        ]
        for offset in range(0, len(missing_ids), 500):
            chunk = missing_ids[offset : offset + 500]
            placeholders = ", ".join("?" for _ in chunk)
            rows = conn.execute(
                "SELECT id, full_text FROM sentences WHERE id IN (%s)" % placeholders,
                chunk,
            ).fetchall()
            for row in rows:
                forms = _word_forms(None, str(row["full_text"]))
                conn.execute(
                    "INSERT INTO sentence_forms(sentence_id, word_form_list) VALUES (?, ?)",
                    (int(row["id"]), " ".join(forms)),
                )
        _mark_corpus_migration_completed(conn, SENTENCE_FORMS_BACKFILL_KEY)
    except sqlite3.Error:
        return


def _backfill_sentence_ngrams(conn: sqlite3.Connection) -> None:
    if _corpus_migration_completed(conn, SENTENCE_NGRAMS_BACKFILL_KEY):
        return
    try:
        cursor = conn.execute("SELECT id, full_text FROM sentences ORDER BY id")
        while True:
            rows = cursor.fetchmany(500)
            if not rows:
                break
            for row in rows:
                _insert_sentence_ngrams(conn, int(row["id"]), str(row["full_text"]))
        _mark_corpus_migration_completed(conn, SENTENCE_NGRAMS_BACKFILL_KEY)
    except sqlite3.Error:
        return


def _ensure_cjk_fts_schema(conn: sqlite3.Connection) -> bool:
    """Create the trigram index when the bundled SQLite supports it."""
    try:
        conn.executescript(CJK_FTS_SCHEMA)
        return True
    except sqlite3.Error:
        # The manual 2/3-character index remains a compatibility fallback for
        # SQLite builds compiled without FTS5's trigram tokenizer.
        return False


def _backfill_cjk_fts(conn: sqlite3.Connection) -> None:
    if _corpus_migration_completed(conn, CJK_FTS_BACKFILL_KEY):
        indexed_count = int(conn.execute("SELECT COUNT(*) FROM fts_cjk").fetchone()[0])
        expected_count = int(
            conn.execute("SELECT COUNT(DISTINCT sentence_id) FROM sentence_ngrams").fetchone()[0]
        )
        if indexed_count >= expected_count:
            return
    try:
        cursor = conn.execute("SELECT id, full_text FROM sentences ORDER BY id")
        while True:
            rows = cursor.fetchmany(500)
            if not rows:
                break
            for row in rows:
                _insert_cjk_fts(conn, int(row["id"]), str(row["full_text"]))
        _mark_corpus_migration_completed(conn, CJK_FTS_BACKFILL_KEY)
    except sqlite3.Error:
        return


def _insert_cjk_fts(conn: sqlite3.Connection, sentence_id: int, full_text: str) -> None:
    if not contains_unsegmented_script(full_text) or not _table_exists(conn, "fts_cjk"):
        return
    conn.execute(
        "INSERT OR REPLACE INTO fts_cjk(rowid, text) VALUES (?, ?)",
        (int(sentence_id), full_text),
    )


def _insert_sentence_ngrams(
    conn: sqlite3.Connection, sentence_id: int, full_text: str
) -> None:
    if not contains_unsegmented_script(full_text):
        return
    normalized = normalize_form(full_text)
    ngrams = {
        normalized[index : index + width]
        for width in (2, 3)
        for index in range(max(0, len(normalized) - width + 1))
    }
    if not ngrams:
        return
    conn.executemany(
        "INSERT OR IGNORE INTO sentence_ngrams(ngram, sentence_id) VALUES (?, ?)",
        ((ngram, int(sentence_id)) for ngram in sorted(ngrams)),
    )


def _corpus_migration_completed(conn: sqlite3.Connection, key: str) -> bool:
    try:
        return (
            conn.execute("SELECT 1 FROM corpus_meta WHERE key = ? LIMIT 1", (key,)).fetchone()
            is not None
        )
    except sqlite3.Error:
        return False


def _mark_corpus_migration_completed(conn: sqlite3.Connection, key: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO corpus_meta(key, value) VALUES (?, '1')",
        (key,),
    )


def _word_forms(word_map: Optional[Dict[str, str]], full_text: str) -> List[str]:
    if word_map:
        return sorted({form for form in word_map if form})
    return sorted({normalize_form(token.text) for token in split_text_tokens(full_text) if token.is_word})


def _row_value(row: sqlite3.Row | Tuple, key: str) -> int:
    if isinstance(row, sqlite3.Row):
        return int(row[key])
    return int(row[0])
