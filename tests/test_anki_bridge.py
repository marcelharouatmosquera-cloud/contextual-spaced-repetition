from __future__ import annotations

import sqlite3
import unittest

import contextual_review.anki_bridge as bridge
from contextual_review.anki_bridge import (
    CardAnswerError,
    answer_review_task,
    build_answer_plan,
    build_due_search_query,
    build_future_search_query,
    collect_due_cards,
    restore_answer_snapshot,
)
from contextual_review.config import normalize_config
from contextual_review.types import ReviewTask


class FakeScheduler:
    today = 100

    def __init__(self) -> None:
        self.answers = []

    def answerCard(self, card, ease: int) -> None:
        if not card.timer_started:
            raise TypeError("unsupported operand type(s) for -: 'float' and 'NoneType'")
        self.answers.append((card.id, ease))


class FakeCollection:
    def __init__(self, scheduler=None, missing_card_ids=None) -> None:
        self.sched = scheduler or FakeScheduler()
        self.updated = False
        self.decks = FakeDecks()
        self.missing_card_ids = set(missing_card_ids or [])

    def get_card(self, card_id: int):
        if card_id in self.missing_card_ids:
            raise KeyError(card_id)
        return FakeCard(card_id)

    def update(self) -> None:
        self.updated = True


class ManualCollection:
    def __init__(self, card_ids) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.sched = FakeScheduler()
        self.updated = False
        self.saved = False
        self._create_schema()
        for card_id in card_ids:
            self._insert_card(card_id)

    def _create_schema(self) -> None:
        self.db.execute(
            """
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY,
                nid INTEGER,
                did INTEGER,
                ord INTEGER,
                mod INTEGER,
                usn INTEGER,
                type INTEGER,
                queue INTEGER,
                due INTEGER,
                ivl INTEGER,
                factor INTEGER,
                reps INTEGER,
                lapses INTEGER,
                left INTEGER,
                odue INTEGER,
                odid INTEGER,
                flags INTEGER,
                data TEXT
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE revlog (
                id INTEGER PRIMARY KEY,
                cid INTEGER,
                usn INTEGER,
                ease INTEGER,
                ivl INTEGER,
                lastIvl INTEGER,
                factor INTEGER,
                time INTEGER,
                type INTEGER
            )
            """
        )

    def _insert_card(self, card_id: int) -> None:
        self.db.execute(
            """
            INSERT INTO cards
            VALUES (?, 1, 1, 0, 0, 0, 2, 2, 100, 5, 2500, 0, 0, 0, 0, 0, 0, '')
            """,
            (card_id,),
        )
        self.db.commit()

    def usn(self) -> int:
        return 7

    def save(self) -> None:
        self.saved = True
        self.db.commit()

    def update(self) -> None:
        self.updated = True

    def get_card(self, card_id: int):
        return FakeCard(card_id)

    def card_row(self, card_id: int):
        return self.db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()

    def revlog_count(self) -> int:
        return int(self.db.execute("SELECT COUNT(*) FROM revlog").fetchone()[0])


class FakeDecks:
    def selected(self) -> int:
        return 1

    def get(self, deck_id: int):
        return {"name": "Vocabulary"}


class FakeCard:
    def __init__(self, card_id: int) -> None:
        self.id = card_id
        self.timer_started = None

    def start_timer(self) -> None:
        self.timer_started = 1.0


class FakeMw:
    def __init__(self, collection=None) -> None:
        self.col = collection or FakeCollection()
        self.checkpoints = []
        self.reset_called = False

    def checkpoint(self, name: str) -> None:
        self.checkpoints.append(name)

    def reset(self) -> None:
        self.reset_called = True


class SnakeCaseScheduler:
    today = 100

    def __init__(self) -> None:
        self.answers = []

    def answer_card(self, card, ease: int) -> None:
        self.answers.append((card.id, ease))


class FailingScheduler:
    today = 100

    def __init__(self, fail_on_card_id: int) -> None:
        self.fail_on_card_id = fail_on_card_id
        self.answers = []

    def answerCard(self, card, ease: int) -> None:
        if card.id == self.fail_on_card_id:
            raise RuntimeError("boom")
        self.answers.append((card.id, ease))


class DirectionCollection:
    def __init__(self, cards, scheduler=None):
        self.sched = scheduler or FakeScheduler()
        self.decks = FakeDecks()
        self.cards = {card.id: card for card in cards}

    def find_cards(self, query: str):
        return sorted(self.cards)

    def get_card(self, card_id: int):
        return self.cards[int(card_id)]


class DirectionNote:
    def __init__(self, russian: str, english: str, templates):
        self.russian = russian
        self.english = english
        self.templates = templates

    def keys(self):
        return ["Russian", "English"]

    def __getitem__(self, key: str):
        if key == "Russian":
            return self.russian
        if key == "English":
            return self.english
        raise KeyError(key)

    def note_type(self):
        return {"name": "Language", "tmpls": self.templates}

    def model(self):
        return {"name": "Language", "tmpls": self.templates}


class DirectionCard:
    queue = 2
    type = 2
    due = 100
    ivl = 5
    factor = 2500
    odid = 0

    def __init__(self, card_id: int, note: DirectionNote, ordinal: int):
        self.id = card_id
        self._note = note
        self.ord = ordinal

    def note(self):
        return self._note


class FlexibleNote:
    def __init__(self, fields, templates):
        self.fields = dict(fields)
        self.templates = templates

    def keys(self):
        return list(self.fields)

    def __getitem__(self, key: str):
        return self.fields[key]

    def note_type(self):
        return {"name": "Senren", "tmpls": self.templates}

    def model(self):
        return self.note_type()


class AnkiBridgeTests(unittest.TestCase):
    def test_card_rows_are_loaded_in_one_database_query(self) -> None:
        collection = ManualCollection([1, 2, 3])

        class CountingDb:
            def __init__(self, db) -> None:
                self.db = db
                self.select_count = 0

            def execute(self, sql, params=()):
                if sql.lstrip().upper().startswith("SELECT"):
                    self.select_count += 1
                return self.db.execute(sql, params)

        db = CountingDb(collection.db)

        rows = bridge._read_card_rows(db, [1, 2, 3])

        self.assertEqual(set(rows), {1, 2, 3})
        self.assertEqual(db.select_count, 1)

    def test_build_due_search_query_scopes_to_current_deck(self) -> None:
        mw = FakeMw()
        config = normalize_config({"search_query": "is:due"})

        self.assertEqual(build_due_search_query(mw, config), '(is:due) -is:new deck:"Vocabulary"')

    def test_build_future_search_query_scopes_to_current_deck(self) -> None:
        mw = FakeMw()
        config = normalize_config({"future_due_days": 3})

        self.assertEqual(
            build_future_search_query(mw, config),
            '(prop:due<=3 -card:2 -card:3 -card:Reverse) -is:new deck:"Vocabulary"',
        )

    def test_build_future_search_query_preserves_quoted_custom_terms(self) -> None:
        mw = FakeMw()
        config = normalize_config(
            {
                "deck_scope": "all",
                "future_due_days": 3,
                "custom_search_query": 'is:due deck:"Spanish Vocabulary" -tag:"hard words"',
            }
        )

        self.assertEqual(
            build_future_search_query(mw, config),
            '(prop:due<=3 deck:"Spanish Vocabulary" -tag:"hard words") -is:new',
        )

    def test_build_due_search_query_prefers_custom_filter_for_reverse_exclusion(self) -> None:
        mw = FakeMw()
        config = normalize_config({"custom_search_query": "is:due -card:Reverse"})

        self.assertEqual(build_due_search_query(mw, config), '(is:due -card:Reverse) -is:new deck:"Vocabulary"')

    def test_friendly_study_options_build_due_and_new_query(self) -> None:
        mw = FakeMw()
        config = normalize_config(
            {"custom_search_query": "is:due -card:Reverse", "include_new_cards": True}
        )

        self.assertEqual(
            build_due_search_query(mw, config),
            '((is:due -card:Reverse) OR (is:new -card:Reverse)) deck:"Vocabulary"',
        )

    def test_new_card_limit_is_enforced(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        note = DirectionNote("dom", "house", templates)
        cards = [DirectionCard(index, note, 0) for index in range(1, 5)]
        for card in cards:
            card.queue = 0
            card.type = 0
        mw = FakeMw(DirectionCollection(cards))
        config = normalize_config(
            {
                "target_field": "Russian",
                "language": "ru",
                "include_due_cards": False,
                "include_new_cards": True,
                "max_new_cards": 2,
                "require_target_on_question": False,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(sorted({card.card_id for card in due_cards}), [1, 2])

    def test_collect_due_cards_skips_cards_without_target_field_on_question(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"},
            {"name": "Production", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("дом", "house", templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0), DirectionCard(2, note, 1)]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "language": "ru",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [1])

    def test_unknown_question_direction_is_skipped_by_default(self) -> None:
        templates = [{"name": "Unknown", "qfmt": "{{FrontSide}}", "afmt": "{{German}}"}]
        note = FlexibleNote({"German": "der Hund", "English": "the dog"}, templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0)]))
        config = normalize_config(
            {
                "target_field": "German",
                "language": "de",
                "custom_search_query": "is:due",
            }
        )

        self.assertEqual(collect_due_cards(mw, config), [])

    def test_collect_due_cards_honors_included_card_templates(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"},
            {"name": "Production", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("дом", "house", templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0), DirectionCard(2, note, 1)]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "language": "ru",
                "custom_search_query": "is:due",
                "require_target_on_question": False,
                "included_card_templates": ["Production"],
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [2])
        self.assertEqual(due_cards.today_card_ids, frozenset({2}))

    def test_collect_due_cards_skips_filtered_deck_cards(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        note = DirectionNote("dom", "house", templates)
        normal = DirectionCard(1, note, 0)
        filtered = DirectionCard(2, note, 0)
        filtered.odid = 123
        mw = FakeMw(DirectionCollection([normal, filtered]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "language": "ru",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [1])

    def test_collect_due_cards_reads_dictionary_field(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        note = DirectionNote("dom", "<b>house</b>", templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0)]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "language": "ru",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(due_cards[0].target_word, "dom")
        self.assertEqual(due_cards[0].definition, "house")

    def test_collect_due_cards_displays_full_target_field_but_matches_content_word(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{German}}", "afmt": "{{English}}"}]
        note = FlexibleNote({"German": "der Monat", "English": "month"}, templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0)]))
        config = normalize_config(
            {
                "target_field": "German",
                "language": "de",
                "custom_search_query": "is:due",
                "target_extraction_mode": "content_words",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(len(due_cards), 1)
        self.assertEqual(due_cards[0].target_word, "der Monat")
        self.assertEqual(due_cards[0].word_form, "monat")
        self.assertEqual(due_cards[0].match_key, "monat")
        self.assertEqual(due_cards[0].definition, "month")

    def test_collect_due_cards_reads_multiple_solution_field_types(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{word}}", "afmt": "{{definition}}"}]
        note = FlexibleNote(
            {
                "word": "\u98df\u3079\u308b",
                "reading": "\u305f\u3079\u308b",
                "definition": "<b>to eat</b>",
                "picture": '<img src="meal.jpg">',
                "wordAudio": "[sound:eat.mp3]",
            },
            templates,
        )
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0)]))
        config = normalize_config(
            {
                "target_field": "word",
                "language": "ja",
                "custom_search_query": "is:due",
                "solution_fields": [
                    {"field": "reading", "display": "text"},
                    {"field": "definition", "display": "text"},
                    {"field": "picture", "display": "image"},
                    {"field": "wordAudio", "display": "audio", "autoplay": True},
                ],
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(len(due_cards), 1)
        fields = due_cards[0].solution_fields
        self.assertEqual(
            [(field.field, field.display) for field in fields],
            [
                ("reading", "text"),
                ("definition", "text"),
                ("picture", "image"),
                ("wordAudio", "audio"),
            ],
        )
        self.assertEqual(fields[1].text, "to eat")
        self.assertEqual(fields[2].media, ("meal.jpg",))
        self.assertEqual(fields[3].media, ("eat.mp3",))
        self.assertTrue(fields[3].autoplay)

    def test_collect_due_cards_falls_back_to_translation_field(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        note = DirectionNote("dom", "<b>house</b>", templates)
        mw = FakeMw(DirectionCollection([DirectionCard(1, note, 0)]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "Missing",
                "language": "ru",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(due_cards[0].definition, "house")
        self.assertEqual(due_cards[0].interval, 5)
        self.assertEqual(due_cards[0].factor, 2500)

    def test_collect_due_cards_applies_max_after_priority_sort(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        first_note = DirectionNote("today", "today", templates)
        overdue_note = DirectionNote("overdue", "overdue", templates)
        first = DirectionCard(1, first_note, 0)
        overdue = DirectionCard(2, overdue_note, 0)
        first.due = 100
        overdue.due = 90
        mw = FakeMw(DirectionCollection([first, overdue]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "custom_search_query": "is:due",
                "max_due_cards": 1,
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [2])
        self.assertEqual(due_cards.today_card_ids, frozenset({1, 2}))

    def test_collect_due_cards_limits_distinct_cards_not_target_words(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        phrase = DirectionCard(1, DirectionNote("first second", "phrase", templates), 0)
        single = DirectionCard(2, DirectionNote("third", "single", templates), 0)
        phrase.due = 90
        single.due = 100
        mw = FakeMw(DirectionCollection([phrase, single]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "custom_search_query": "is:due",
                "target_extraction_mode": "all_words",
                "max_due_cards": 2,
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [1, 1, 2])

    def test_answer_review_task_uses_scheduler_eases(self) -> None:
        mw = FakeMw()
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        summary = answer_review_task(mw, task, ["review"], config)

        self.assertEqual(mw.checkpoints, ["Contextual Review"])
        self.assertEqual(mw.col.sched.answers, [(10, 1), (20, 3)])
        self.assertEqual(summary.answered_card_ids, [10, 20])
        self.assertEqual(summary.unknown_card_ids, [10])
        self.assertEqual(summary.known_card_ids, [20])
        self.assertTrue(mw.col.updated)
        self.assertTrue(mw.reset_called)

    def test_build_answer_plan_deduplicates_card_ids_and_prefers_unknown(self) -> None:
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review words.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "word": [10, 20]},
        )

        answers = build_answer_plan(task, ["word"], config)

        self.assertEqual([(answer.card_id, answer.ease, answer.is_unknown) for answer in answers], [(10, 1, True), (20, 1, True)])
        self.assertEqual(answers[0].match_keys, ["review", "word"])

    def test_build_answer_plan_accepts_explicit_unknown_card_ids(self) -> None:
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="She went home.",
            translation=None,
            tokens=[],
            card_ids_by_key={"go": [12345]},
        )

        answers = build_answer_plan(task, [], config, unknown_card_ids=["12345"])

        self.assertEqual([(answer.card_id, answer.ease, answer.is_unknown) for answer in answers], [(12345, 1, True)])

    def test_answer_review_task_uses_snake_case_scheduler(self) -> None:
        scheduler = SnakeCaseScheduler()
        mw = FakeMw(FakeCollection(scheduler=scheduler))
        config = normalize_config({})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10]},
        )

        answer_review_task(mw, task, [], config)

        self.assertEqual(scheduler.answers, [(10, 3)])

    def test_answer_review_task_batches_arbitrary_cards_with_contextual_scheduler(self) -> None:
        mw = FakeMw(ManualCollection([10, 20]))
        mw.checkpoint = None
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        summary = answer_review_task(mw, task, ["review"], config)

        self.assertEqual(summary.answered_card_ids, [10, 20])
        self.assertEqual(summary.unknown_card_ids, [10])
        self.assertEqual(mw.checkpoints, [])
        self.assertEqual(mw.col.sched.answers, [])
        self.assertTrue(mw.col.updated)
        self.assertTrue(mw.reset_called)
        self.assertEqual(mw.col.revlog_count(), 2)
        self.assertEqual(mw.col.card_row(10)["type"], 3)
        self.assertEqual(mw.col.card_row(10)["queue"], 1)
        self.assertEqual(mw.col.card_row(10)["ivl"], 0)
        self.assertEqual(mw.col.card_row(10)["left"], 1001)
        self.assertEqual(mw.col.card_row(10)["lapses"], 1)
        self.assertGreater(mw.col.card_row(20)["due"], 100)
        self.assertIsNotNone(summary.undo_snapshot)

        restore_answer_snapshot(mw, summary.undo_snapshot)

        self.assertEqual(mw.col.revlog_count(), 0)
        self.assertEqual(mw.col.card_row(10)["ivl"], 5)
        self.assertEqual(mw.col.card_row(10)["lapses"], 0)
        self.assertEqual(mw.col.card_row(20)["due"], 100)

    def test_contextual_scheduler_refuses_filtered_deck_cards(self) -> None:
        mw = FakeMw(ManualCollection([10]))
        mw.checkpoint = None
        mw.col.db.execute("UPDATE cards SET odid = 123, odue = 100 WHERE id = 10")
        mw.col.db.commit()
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10]},
        )

        with self.assertRaisesRegex(RuntimeError, "filtered-deck card"):
            answer_review_task(mw, task, [], config)

        self.assertEqual(mw.col.revlog_count(), 0)
        self.assertEqual(mw.col.card_row(10)["odid"], 123)

    def test_answer_review_task_prefers_native_scheduler_when_database_is_available(self) -> None:
        mw = FakeMw(ManualCollection([10, 20]))
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        summary = answer_review_task(mw, task, ["review"], config)

        self.assertEqual(mw.checkpoints, ["Contextual Review"])
        self.assertEqual(mw.col.sched.answers, [(10, 1), (20, 3)])
        self.assertEqual(mw.col.revlog_count(), 0)
        self.assertEqual(summary.answered_card_ids, [10, 20])
        self.assertEqual(summary.unknown_card_ids, [10])
        self.assertEqual(summary.known_card_ids, [20])
        self.assertIsNone(summary.undo_snapshot)

    def test_contextual_scheduler_restores_card_rows_after_write_failure(self) -> None:
        mw = FakeMw(ManualCollection([10]))
        mw.checkpoint = None
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10]},
        )
        original_insert = bridge._insert_revlog_row
        try:
            bridge._insert_revlog_row = lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("revlog failed")
            )

            with self.assertRaisesRegex(RuntimeError, "restored the previous card state"):
                answer_review_task(mw, task, ["review"], config)
        finally:
            bridge._insert_revlog_row = original_insert

        self.assertEqual(mw.col.revlog_count(), 0)
        self.assertEqual(mw.col.card_row(10)["type"], 2)
        self.assertEqual(mw.col.card_row(10)["queue"], 2)
        self.assertEqual(mw.col.card_row(10)["ivl"], 5)
        self.assertEqual(mw.col.card_row(10)["lapses"], 0)

    def test_answer_review_task_preflights_missing_cards_before_checkpoint(self) -> None:
        mw = FakeMw(FakeCollection(missing_card_ids={20}))
        config = normalize_config({})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        with self.assertRaisesRegex(RuntimeError, "Could not load card"):
            answer_review_task(mw, task, [], config)

        self.assertEqual(mw.checkpoints, [])
        self.assertEqual(mw.col.sched.answers, [])

    def test_answer_review_task_reports_partial_scheduler_failure(self) -> None:
        scheduler = FailingScheduler(fail_on_card_id=20)
        mw = FakeMw(FakeCollection(scheduler=scheduler))
        config = normalize_config({})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review cards.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        with self.assertRaises(CardAnswerError) as raised:
            answer_review_task(mw, task, [], config)

        self.assertEqual(mw.checkpoints, ["Contextual Review"])
        self.assertEqual(raised.exception.answered_card_ids, [10])
        self.assertIn("after answering 1 card", str(raised.exception))
        self.assertTrue(mw.col.updated)
        self.assertTrue(mw.reset_called)


if __name__ == "__main__":
    unittest.main()
