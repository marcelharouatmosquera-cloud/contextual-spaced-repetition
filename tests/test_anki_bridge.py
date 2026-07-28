from __future__ import annotations

import sqlite3
import time
import unittest

import contextual_review.anki_bridge as bridge
from contextual_review.anki_bridge import (
    answer_review_task,
    build_answer_plan,
    build_due_search_query,
    build_future_search_query,
    collect_due_cards,
)
from contextual_review.config import normalize_config
from contextual_review.types import ReviewTask


class FakeScheduler:
    today = 100

    def __init__(self) -> None:
        self.answers = []


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
    """Read-only card-table fixture for bulk state inspection tests."""

    def __init__(self, card_ids) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """
            CREATE TABLE cards (
                id INTEGER PRIMARY KEY, nid INTEGER, did INTEGER, ord INTEGER,
                mod INTEGER, usn INTEGER, type INTEGER, queue INTEGER,
                due INTEGER, ivl INTEGER, factor INTEGER, reps INTEGER,
                lapses INTEGER, left INTEGER, odue INTEGER, odid INTEGER,
                flags INTEGER, data TEXT
            )
            """
        )
        self.db.executemany(
            "INSERT INTO cards VALUES (?, 1, 1, 0, 0, 0, 2, 2, 100, 5, 2500, 0, 0, 0, 0, 0, 0, '')",
            ((int(card_id),) for card_id in card_ids),
        )
        self.db.commit()


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


class GradeNowCard(FakeCard):
    def __init__(self, card_id: int, state) -> None:
        super().__init__(card_id)
        self.queue = state["queue"]
        self.type = state["type"]
        self.due = state["due"]
        self.nid = state.get("nid", card_id)
        self.did = state.get("did", 1)
        self.odid = state.get("odid", 0)


class GradeNowBackend:
    def __init__(self, collection, fail_rating=None) -> None:
        self.collection = collection
        self.fail_rating = fail_rating
        self.calls = []

    def grade_now(self, *, card_ids, rating: int) -> None:
        self.calls.append((list(card_ids), rating))
        if rating == self.fail_rating:
            raise RuntimeError("grade failed")
        for card_id in card_ids:
            if rating == 0:
                self.collection.states[card_id] = {
                    "queue": 1,
                    "type": 3,
                    "due": 1_800_000_000,
                    "nid": self.collection.states[card_id].get("nid", card_id),
                    "did": self.collection.states[card_id].get("did", 1),
                }
            else:
                self.collection.states[card_id] = {
                    "queue": 2,
                    "type": 2,
                    "due": self.collection.sched.today + 5,
                    "nid": self.collection.states[card_id].get("nid", card_id),
                    "did": self.collection.states[card_id].get("did", 1),
                }


class GradeNowCollection(FakeCollection):
    def __init__(self, card_ids, fail_rating=None) -> None:
        super().__init__()
        self.states = {
            card_id: {"queue": 2, "type": 2, "due": self.sched.today, "nid": card_id, "did": 1}
            for card_id in card_ids
        }
        self._backend = GradeNowBackend(self, fail_rating=fail_rating)
        self.undo_names = []
        self.merged_entries = []
        self.undo_called = False
        self._undo_snapshot = None

    def get_card(self, card_id: int):
        if card_id not in self.states:
            raise KeyError(card_id)
        return GradeNowCard(card_id, self.states[card_id])

    def add_custom_undo_entry(self, name: str) -> int:
        self.undo_names.append(name)
        self._undo_snapshot = {card_id: dict(state) for card_id, state in self.states.items()}
        return 42

    def merge_undo_entries(self, target: int) -> None:
        self.merged_entries.append(target)

    def undo(self) -> None:
        self.undo_called = True
        if self._undo_snapshot is not None:
            self.states = {
                card_id: dict(state) for card_id, state in self._undo_snapshot.items()
            }

    def card_ids_of_note(self, note_id: int):
        return [
            card_id for card_id, state in self.states.items()
            if state.get("nid", card_id) == note_id
        ]


class SiblingScheduler(FakeScheduler):
    def __init__(self, collection) -> None:
        super().__init__()
        self.collection = collection
        self.buried = []

    def bury_cards(self, card_ids, manual=True) -> None:
        self.buried.append((list(card_ids), manual))
        for card_id in card_ids:
            self.collection.states[card_id]["queue"] = -2


class SiblingDecks(FakeDecks):
    def config_dict_for_deck_id(self, deck_id: int):
        return {
            "new": {"bury": False},
            "rev": {"bury": True},
            "buryInterdayLearning": True,
        }


class SiblingGradeNowCollection(GradeNowCollection):
    def __init__(self) -> None:
        super().__init__([10, 11, 12])
        self.states[10].update({"nid": 1, "queue": 2, "type": 2, "due": 100})
        self.states[11].update({"nid": 1, "queue": 2, "type": 2, "due": 100})
        self.states[12].update({"nid": 1, "queue": 0, "type": 0, "due": 1})
        self.decks = SiblingDecks()
        self.sched = SiblingScheduler(self)


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

        self.assertEqual(
            build_due_search_query(mw, config),
            '((is:due) -is:new) -is:buried deck:"Vocabulary"',
        )

    def test_build_future_search_query_scopes_to_current_deck(self) -> None:
        mw = FakeMw()
        config = normalize_config({"future_due_days": 3})

        self.assertEqual(
            build_future_search_query(mw, config),
            '((prop:due<=3 -card:2 -card:3 -card:Reverse) -is:new) -is:buried deck:"Vocabulary"',
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
            '((prop:due<=3 deck:"Spanish Vocabulary" -tag:"hard words") -is:new) -is:buried',
        )

    def test_build_due_search_query_prefers_custom_filter_for_reverse_exclusion(self) -> None:
        mw = FakeMw()
        config = normalize_config({"custom_search_query": "is:due -card:Reverse"})

        self.assertEqual(
            build_due_search_query(mw, config),
            '((is:due -card:Reverse) -is:new) -is:buried deck:"Vocabulary"',
        )

    def test_friendly_study_options_build_due_and_new_query(self) -> None:
        mw = FakeMw()
        config = normalize_config(
            {"custom_search_query": "is:due -card:Reverse", "include_new_cards": True}
        )

        self.assertEqual(
            build_due_search_query(mw, config),
            '(((is:due -card:Reverse) OR (is:new -card:Reverse))) -is:buried deck:"Vocabulary"',
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

    def test_collect_due_cards_admits_explicit_recall_template_without_target_on_question(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"},
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("dom", "house", templates)
        recall = DirectionCard(2, note, 1)
        recall.nid = 55
        mw = FakeMw(DirectionCollection([recall]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "language": "ru",
                "custom_search_query": "is:due",
                "included_card_templates": ["Recognition"],
                "recall_templates": ["Recall"],
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [2])
        self.assertEqual(due_cards[0].direction, "recall")
        self.assertEqual(due_cards[0].note_id, 55)
        self.assertEqual(due_cards[0].definition, "house")

    def test_recall_hint_never_uses_the_target_field_itself(self) -> None:
        templates = [
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("dom", "house", templates)
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "Russian",
                "solution_fields": [{"field": "Russian", "display": "text"}],
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, note, 0)])),
            config,
        )

        self.assertEqual(len(due_cards), 1)
        self.assertEqual(due_cards[0].direction, "recall")
        self.assertEqual(due_cards[0].definition, "house")

    def test_recall_card_without_a_non_target_hint_is_skipped(self) -> None:
        templates = [
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("dom", "", templates)
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "solution_fields": [{"field": "Russian", "display": "text"}],
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, note, 0)])),
            config,
        )

        self.assertEqual(due_cards, [])

    def test_recall_only_profile_excludes_unmapped_templates(self) -> None:
        templates = [
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
            {"name": "Unrelated", "qfmt": "{{Extra}}", "afmt": "{{Russian}}"},
        ]
        note = FlexibleNote(
            {"Russian": "dom", "English": "house", "Extra": "metadata"},
            templates,
        )
        recall = DirectionCard(1, note, 0)
        unrelated = DirectionCard(2, note, 1)
        recall.nid = 10
        unrelated.nid = 20
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
                "require_target_on_question": False,
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([recall, unrelated])),
            config,
        )

        self.assertEqual([card.card_id for card in due_cards], [1])
        self.assertEqual(due_cards[0].direction, "recall")

    def test_recall_template_label_does_not_override_an_unclassified_front(self) -> None:
        templates = [
            {"name": "Card 2", "qfmt": "{{Picture}}", "afmt": "{{Russian}}"},
        ]
        note = FlexibleNote(
            {"Russian": "dom", "English": "house", "Picture": "house.jpg"},
            templates,
        )
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "recall_templates": ["Card 2"],
                "custom_search_query": "is:due",
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, note, 0)])),
            config,
        )

        self.assertEqual(due_cards, [])

    def test_template_in_both_direction_lists_uses_question_fields(self) -> None:
        recognition_note = DirectionNote(
            "dom",
            "house",
            [{"name": "Shared", "qfmt": "{{Russian}}", "afmt": "{{English}}"}],
        )
        recall_note = DirectionNote(
            "dom",
            "house",
            [{"name": "Shared", "qfmt": "{{English}}", "afmt": "{{Russian}}"}],
        )
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "included_card_templates": ["Shared"],
                "recall_templates": ["Shared"],
                "custom_search_query": "is:due",
            }
        )

        recognition = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, recognition_note, 0)])),
            config,
        )
        recall = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(2, recall_note, 0)])),
            config,
        )

        self.assertEqual(recognition[0].direction, "recognition")
        self.assertEqual(recall[0].direction, "recall")

    def test_shared_template_name_treats_typed_target_input_as_recall(self) -> None:
        note = DirectionNote(
            "dom",
            "house",
            [
                {
                    "name": "Shared",
                    "qfmt": "{{English}}<br>{{type:Russian}}",
                    "afmt": "{{Russian}}",
                }
            ],
        )
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "included_card_templates": ["Shared"],
                "recall_templates": ["Shared"],
                "custom_search_query": "is:due",
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, note, 0)])),
            config,
        )

        self.assertEqual(len(due_cards), 1)
        self.assertEqual(due_cards[0].direction, "recall")

    def test_hidden_target_does_not_satisfy_recognition_front_requirement(self) -> None:
        note = DirectionNote(
            "dom",
            "house",
            [
                {
                    "name": "Hidden target",
                    "qfmt": '<div style="display:none">{{Russian}}</div>{{English}}',
                    "afmt": "{{Russian}}",
                }
            ],
        )
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([DirectionCard(1, note, 0)])),
            config,
        )

        self.assertEqual(due_cards, [])

    def test_collect_due_cards_defers_recall_when_same_note_recognition_is_due(self) -> None:
        templates = [
            {"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"},
            {"name": "Recall", "qfmt": "{{English}}", "afmt": "{{Russian}}"},
        ]
        note = DirectionNote("dom", "house", templates)
        recognition = DirectionCard(20, note, 0)
        recall = DirectionCard(10, note, 1)
        recognition.nid = recall.nid = 77
        recognition.due = 100
        recall.due = 80
        config = normalize_config(
            {
                "target_field": "Russian",
                "dictionary_field": "English",
                "included_card_templates": ["Recognition"],
                "recall_templates": ["Recall"],
                "custom_search_query": "is:due",
            }
        )

        due_cards = collect_due_cards(
            FakeMw(DirectionCollection([recognition, recall])),
            config,
        )

        self.assertEqual([card.card_id for card in due_cards], [20])
        self.assertEqual(due_cards[0].direction, "recognition")

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

    def test_collect_due_cards_suppresses_due_review_sibling_from_own_queue(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        note = DirectionNote("dom", "house", templates)
        first = DirectionCard(1, note, 0)
        sibling = DirectionCard(2, note, 0)
        first.nid = 55
        sibling.nid = 55
        first.due = 90
        sibling.due = 100
        collection = DirectionCollection([first, sibling])
        collection.decks = SiblingDecks()
        mw = FakeMw(collection)
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
        self.assertEqual(due_cards.today_card_ids, frozenset({1}))

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

    def test_due_learning_card_enters_limited_batch_before_overdue_reviews(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        learning = DirectionCard(1, DirectionNote("learn", "learn", templates), 0)
        learning.queue = 1
        learning.type = 3
        learning.due = int(time.time()) - 1
        overdue = DirectionCard(2, DirectionNote("overdue", "overdue", templates), 0)
        overdue.due = 1
        mw = FakeMw(DirectionCollection([learning, overdue]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "custom_search_query": "is:due",
                "max_due_cards": 1,
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual([card.card_id for card in due_cards], [1])
        self.assertTrue(due_cards[0].is_learning_due)

    def test_collect_due_cards_excludes_intraday_step_before_exact_timestamp(self) -> None:
        templates = [{"name": "Recognition", "qfmt": "{{Russian}}", "afmt": "{{English}}"}]
        learning = DirectionCard(1, DirectionNote("learn", "learn", templates), 0)
        learning.queue = 1
        learning.type = 3
        learning.due = int(time.time()) + 600
        mw = FakeMw(DirectionCollection([learning]))
        config = normalize_config(
            {
                "target_field": "Russian",
                "custom_search_query": "is:due",
                "require_target_on_question": True,
            }
        )

        due_cards = collect_due_cards(mw, config)

        self.assertEqual(due_cards, [])
        self.assertEqual(due_cards.today_card_ids, frozenset())

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

    def test_answer_review_task_maps_scheduler_eases_to_grade_now_ratings(self) -> None:
        mw = FakeMw(GradeNowCollection([10, 20]))
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

        self.assertEqual(mw.col._backend.calls, [([10], 0), ([20], 2)])
        self.assertEqual(mw.col.undo_names, ["Contextual Review"])
        self.assertEqual(summary.answered_card_ids, [10, 20])
        self.assertEqual(summary.unknown_card_ids, [10])
        self.assertEqual(summary.known_card_ids, [20])
        self.assertTrue(mw.col.updated)
        self.assertTrue(mw.reset_called)

    def test_lesson_completion_requires_a_next_step_after_today(self) -> None:
        today = 100

        self.assertFalse(
            bridge._card_state_is_beyond_current_lesson(
                {"card_id": 1, "queue": 1, "type": 3, "due": 1_800_000_000},
                today,
            )
        )
        self.assertFalse(
            bridge._card_state_is_beyond_current_lesson(
                {"card_id": 2, "queue": 3, "type": 3, "due": today},
                today,
            )
        )
        self.assertTrue(
            bridge._card_state_is_beyond_current_lesson(
                {"card_id": 3, "queue": 3, "type": 3, "due": today + 1},
                today,
            )
        )
        self.assertTrue(
            bridge._card_state_is_beyond_current_lesson(
                {"card_id": 4, "queue": 2, "type": 2, "due": today + 10},
                today,
            )
        )

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

    def test_answer_review_task_requires_native_grade_now(self) -> None:
        mw = FakeMw(FakeCollection())
        config = normalize_config({})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10]},
        )

        with self.assertRaisesRegex(RuntimeError, "grade_now batch API is unavailable"):
            answer_review_task(mw, task, [], config)

    def test_answer_review_task_batches_arbitrary_cards_with_anki_grade_now(self) -> None:
        mw = FakeMw(GradeNowCollection([10, 20]))
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
        self.assertEqual(summary.completed_card_ids, [20])
        self.assertEqual(mw.col._backend.calls, [([10], 0), ([20], 2)])
        self.assertEqual(mw.col.undo_names, ["Contextual Review"])
        self.assertEqual(mw.col.merged_entries, [42, 42])
        self.assertTrue(mw.col.updated)
        self.assertTrue(mw.reset_called)

    def test_grade_now_rolls_back_a_partially_graded_sentence(self) -> None:
        mw = FakeMw(GradeNowCollection([10, 20], fail_rating=2))
        config = normalize_config({"known_ease": 3, "unknown_ease": 1})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10], "card": [20]},
        )

        with self.assertRaisesRegex(RuntimeError, "could not grade"):
            answer_review_task(mw, task, ["review"], config)

        self.assertTrue(mw.col.undo_called)
        self.assertEqual(mw.col.states[10]["queue"], 2)
        self.assertEqual(mw.col.states[10]["due"], 100)
        self.assertEqual(mw.col.states[20]["queue"], 2)
        self.assertEqual(mw.col.states[20]["due"], 100)

    def test_grade_now_buries_due_review_sibling_and_honors_new_bury_option(self) -> None:
        mw = FakeMw(SiblingGradeNowCollection())
        config = normalize_config({"known_ease": 3})
        task = ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation=None,
            tokens=[],
            card_ids_by_key={"review": [10]},
        )

        answer_review_task(mw, task, [], config)

        self.assertEqual(mw.col._backend.calls, [([10], 2)])
        self.assertEqual(mw.col.sched.buried, [([11], False)])
        self.assertEqual(mw.col.states[11]["queue"], -2)
        self.assertEqual(mw.col.states[12]["queue"], 0)
        self.assertEqual(mw.col.merged_entries, [42, 42])

    def test_answer_review_task_preflights_missing_cards_before_undo_entry(self) -> None:
        mw = FakeMw(GradeNowCollection([10]))
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

        self.assertEqual(mw.col.undo_names, [])
        self.assertEqual(mw.col._backend.calls, [])


if __name__ == "__main__":
    unittest.main()
