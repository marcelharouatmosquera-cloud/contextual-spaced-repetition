#!/usr/bin/env python
"""Run an end-to-end contextual review smoke test without Anki."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_review.anki_bridge import answer_review_task, collect_due_cards
from contextual_review.config import normalize_config
from contextual_review.corpus import initialize_database, insert_sentence, select_review_task
from contextual_review.importer import sentence_word_map
from contextual_review.web import render_task_html


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable smoke results")
    args = parser.parse_args(argv)

    result = run_smoke_review_loop()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print("Smoke review loop passed:")
        print("  selected sentence: %s" % result["sentence"])
        print("  due keys: %s" % ", ".join(result["due_keys"]))
        print("  scheduler answers: %s" % result["answers"])
    return 0


def run_smoke_review_loop() -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "contextual_sentences.db"
        _build_smoke_db(db_path)

        config = normalize_config(
            {
                "database_path": str(db_path),
                "language": "en",
                "deck_scope": "current",
                "custom_search_query": "is:due -is:new",
                "target_field": "Front",
                "matching_mode": "exact_form",
                "known_ease": 3,
                "unknown_ease": 1,
            }
        )
        mw = FakeMw(
            [
                FakeCard(101, "review", due=98),
                FakeCard(102, "cards", due=99),
            ]
        )

        due_cards = collect_due_cards(mw, config)
        task = select_review_task(
            db_path,
            due_cards,
            config.language,
            set(),
            config.candidate_limit,
            config.min_sentence_words,
            config.max_sentence_words,
            config.query_term_limit,
            config.matching_mode,
        )
        if task is None:
            raise AssertionError("No smoke review task was selected")

        html = render_task_html(task)
        summary = answer_review_task(mw, task, ["review"], config)

        expected_answers = [(101, 1), (102, 3)]
        if mw.col.sched.answers != expected_answers:
            raise AssertionError("Expected %s, got %s" % (expected_answers, mw.col.sched.answers))
        if summary.answered_card_ids != [101, 102]:
            raise AssertionError("Unexpected answer summary: %s" % summary)
        if "unknown_keys" not in html or "Show Solution" not in html:
            raise AssertionError("Rendered review HTML is missing bridge payload or controls")
        if mw.checkpoints != ["Contextual Review"]:
            raise AssertionError("Expected one undo checkpoint, got %s" % mw.checkpoints)
        if not mw.col.updated or not mw.reset_called:
            raise AssertionError("Collection update/reset hooks were not called")

        return {
            "sentence": task.full_text,
            "due_keys": sorted(card.match_key for card in due_cards),
            "answers": mw.col.sched.answers,
            "answered_card_ids": summary.answered_card_ids,
            "unknown_card_ids": summary.unknown_card_ids,
            "known_card_ids": summary.known_card_ids,
            "checkpoint_count": len(mw.checkpoints),
            "html_length": len(html),
        }


def _build_smoke_db(db_path: Path) -> None:
    initialize_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        text = "We review cards daily."
        word_map = sentence_word_map(text, "en")
        insert_sentence(conn, "en", text, "We review cards daily.", word_map, source="smoke")
        conn.commit()
    finally:
        conn.close()


class FakeScheduler:
    today = 100

    def __init__(self) -> None:
        self.answers: List[tuple[int, int]] = []

    def answerCard(self, card: "FakeCard", ease: int) -> None:
        if card.timer_started is None:
            raise RuntimeError("card timer was not started")
        self.answers.append((card.id, ease))


class FakeCollection:
    def __init__(self, cards: Sequence["FakeCard"]) -> None:
        self.sched = FakeScheduler()
        self.decks = FakeDecks()
        self.cards = {card.id: card for card in cards}
        self.updated = False

    def find_cards(self, query: str) -> List[int]:
        if "is:due" not in query:
            return []
        return sorted(self.cards)

    def get_card(self, card_id: int) -> "FakeCard":
        return self.cards[int(card_id)]

    def update(self) -> None:
        self.updated = True


class FakeDecks:
    def selected(self) -> int:
        return 1

    def get(self, deck_id: int) -> Dict[str, str]:
        return {"name": "Vocabulary"}


class FakeNote:
    def __init__(self, front: str) -> None:
        self.front = front

    def keys(self) -> List[str]:
        return ["Front"]

    def __getitem__(self, key: str) -> str:
        if key == "Front":
            return self.front
        raise KeyError(key)

    def note_type(self) -> Dict[str, Any]:
        return {
            "name": "Smoke",
            "tmpls": [{"name": "Reading", "qfmt": "{{Front}}", "afmt": "{{Front}}"}],
        }


class FakeCard:
    queue = 2
    type = 2
    ord = 0

    def __init__(self, card_id: int, front: str, due: int) -> None:
        self.id = card_id
        self.due = due
        self._note = FakeNote(front)
        self.timer_started: Optional[float] = None

    def note(self) -> FakeNote:
        return self._note

    def start_timer(self) -> None:
        self.timer_started = 1.0


class FakeMw:
    def __init__(self, cards: Sequence[FakeCard]) -> None:
        self.col = FakeCollection(cards)
        self.checkpoints: List[str] = []
        self.reset_called = False

    def checkpoint(self, name: str) -> None:
        self.checkpoints.append(name)

    def reset(self) -> None:
        self.reset_called = True


if __name__ == "__main__":
    raise SystemExit(main())
