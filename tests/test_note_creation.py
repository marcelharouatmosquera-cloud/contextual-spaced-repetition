from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from contextual_review.config import normalize_config
from contextual_review.note_creation import create_mined_note, export_favorites_to_anki
from contextual_review.types import ReviewTask, TargetWordDefinition


class FakeNote(dict):
    def __init__(self, notetype):
        super().__init__((field["name"], "") for field in notetype["flds"])
        self._notetype = notetype
        self.id = 0
        self.tags = []

    def note_type(self):
        return self._notetype

    def add_tag(self, tag):
        self.tags.append(tag)


class FakeDecks:
    def __init__(self):
        self.created = []
        self.selected_id = 7

    def get(self, deck_id):
        return {"id": deck_id, "name": "Vocabulary" if deck_id == 7 else "Contextual Review Favorites"}

    def id(self, name):
        self.created.append(name)
        return 99

    def current(self):
        return {"id": self.selected_id, "name": "Vocabulary"}

    def select(self, deck_id):
        self.selected_id = int(deck_id)


class FakeScheduler:
    def __init__(self):
        self.repositioned = []
        self.extended = []

    def reposition_new_cards(self, **kwargs):
        self.repositioned.append(kwargs)

    def extend_limits(self, new, rev):
        self.extended.append((new, rev))


class FakeMedia:
    def __init__(self):
        self.paths = []

    def add_file(self, path):
        self.paths.append(path)
        return "mined.mp3"


class FakeModels:
    def __init__(self, favorite_notetype):
        self.favorite_notetype = favorite_notetype

    def by_name(self, name):
        return self.favorite_notetype if name == "Contextual Review Favorite" else None


class FakeCollection:
    def __init__(self):
        self.word_notetype = {
            "name": "Basic (and reversed card)",
            "flds": [
                {"name": "German"},
                {"name": "English"},
                {"name": "Example Sentence"},
                {"name": "Audio"},
            ],
        }
        self.favorite_notetype = {
            "name": "Contextual Review Favorite",
            "flds": [
                {"name": "Sentence"},
                {"name": "Translation"},
                {"name": "Target Words"},
            ],
        }
        self.decks = FakeDecks()
        self.sched = FakeScheduler()
        self.media = FakeMedia()
        self.models = FakeModels(self.favorite_notetype)
        self.notes = {}
        self.added = []
        self.next_note_id = 50
        self.undo_labels = []
        self.merged = []
        self.undo_called = False
        self.search_results = []
        self.generated_cards = {}

    def get_card(self, card_id):
        if card_id == 10:
            source_note = FakeNote(self.word_notetype)
            return SimpleNamespace(
                id=10,
                did=7,
                odid=0,
                queue=2,
                note=lambda: source_note,
                current_deck_id=lambda: 7,
            )
        return SimpleNamespace(id=card_id, queue=0)

    def new_note(self, notetype):
        return FakeNote(notetype)

    def add_note(self, note, deck_id):
        note.id = self.next_note_id
        self.next_note_id += 1
        self.notes[note.id] = note
        self.added.append((note, deck_id))
        self.generated_cards[note.id] = (note.id * 10 + 1, note.id * 10 + 2)

    def card_ids_of_note(self, note_id):
        return self.generated_cards[note_id]

    def find_notes(self, query):
        self.last_query = query
        return list(self.search_results)

    def get_note(self, note_id):
        return self.notes[note_id]

    def add_custom_undo_entry(self, label):
        self.undo_labels.append(label)
        return 42

    def merge_undo_entries(self, target):
        self.merged.append(target)

    def undo(self):
        self.undo_called = True


class NoteCreationTests(unittest.TestCase):
    def _mw(self):
        collection = FakeCollection()
        mw = SimpleNamespace(
            col=collection,
            reset_called=False,
            undo_actions_updated=False,
        )
        mw.reset = lambda: setattr(mw, "reset_called", True)
        mw.update_undo_actions = lambda: setattr(mw, "undo_actions_updated", True)
        return mw

    def test_mining_uses_source_notetype_generates_all_templates_and_repositions_natively(self):
        mw = self._mw()
        task = ReviewTask(
            1,
            "de",
            "Der Hund schläft.",
            None,
            [],
            {"hund": [10]},
            target_words=(TargetWordDefinition(10, "Hund", "dog"),),
        )
        config = normalize_config(
            {
                "target_field": "German",
                "dictionary_field": "English",
                "solution_fields": [
                    {"field": "English", "display": "text"},
                    {"field": "Audio", "display": "audio"},
                ],
            }
        )
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "word.mp3"
            audio.write_bytes(b"audio")
            result = create_mined_note(mw, task, "Hund", "dog", config, audio)

        note, deck_id = mw.col.added[0]
        self.assertEqual(deck_id, 7)
        self.assertEqual(note["German"], "Hund")
        self.assertEqual(note["English"], "dog")
        self.assertEqual(note["Example Sentence"], "Der Hund schläft.")
        self.assertEqual(note["Audio"], "[sound:mined.mp3]")
        self.assertEqual(note.tags, ["mined-word"])
        self.assertEqual(len(result.card_ids), 2)
        self.assertEqual(result.new_limit_increase, 0)
        self.assertEqual(
            mw.col.sched.repositioned,
            [
                {
                    "card_ids": list(result.card_ids),
                    "starting_from": 1,
                    "step_size": 1,
                    "randomize": False,
                    "shift_existing": True,
                }
            ],
        )
        self.assertEqual(mw.col.undo_labels, ["Add Contextual Note"])
        self.assertEqual(mw.col.merged, [42, 42])
        self.assertTrue(mw.reset_called)
        self.assertTrue(mw.undo_actions_updated)

    def test_mining_increases_today_limit_by_actual_generated_card_count(self):
        mw = self._mw()
        task = ReviewTask(
            1,
            "de",
            "Der Hund schläft.",
            None,
            [],
            {"hund": [10]},
            target_words=(TargetWordDefinition(10, "Hund", "dog"),),
        )
        config = normalize_config(
            {
                "target_field": "German",
                "dictionary_field": "English",
                "increase_new_limit_after_mining": True,
            }
        )

        result = create_mined_note(mw, task, "Hund", "dog", config)

        self.assertEqual(result.new_limit_increase, 2)
        self.assertEqual(mw.col.sched.extended, [(2, 0)])
        self.assertEqual(mw.col.decks.selected_id, 7)
        self.assertEqual(mw.col.merged, [42, 42, 42])

    def test_duplicate_mined_word_is_rejected_before_an_undo_entry(self):
        mw = self._mw()
        existing = FakeNote(mw.col.word_notetype)
        existing.id = 77
        existing["German"] = "Hund"
        mw.col.notes[77] = existing
        mw.col.search_results = [77]
        task = ReviewTask(1, "de", "Der Hund.", None, [], {"hund": [10]})
        config = normalize_config(
            {"target_field": "German", "dictionary_field": "English"}
        )

        with self.assertRaisesRegex(ValueError, "already exists"):
            create_mined_note(mw, task, "Hund", "dog", config)

        self.assertEqual(mw.col.undo_labels, [])
        self.assertEqual(mw.col.added, [])

    def test_mining_fills_plain_visible_and_numbered_sentence_field_pairs(self):
        mw = self._mw()
        mw.col.word_notetype = {
            "name": "Russian Core 5000",
            "flds": [
                {"name": "Word"},
                {"name": "Translation"},
                {"name": "Sentence 1"},
                {"name": "Sentence 1 Translation"},
                {"name": "Sentence 2"},
                {"name": "Sentence 2 Translation"},
                {"name": "Audio Word"},
                {"name": "Plain Word"},
                {"name": "Plain Sentence 1"},
                {"name": "Plain Sentence 2"},
            ],
        }
        task = ReviewTask(
            1,
            "ru",
            "Knowledge needs mercy. Mercy needs knowledge.",
            "Knowledge requires mercy. Mercy requires knowledge.",
            [],
            {"mercy": [10]},
        )
        config = normalize_config(
            {
                "target_field": "Plain Word",
                "dictionary_field": "Translation",
                "solution_fields": [
                    {"field": "Translation", "display": "text"},
                    {"field": "Audio Word", "display": "audio"},
                ],
            }
        )

        create_mined_note(mw, task, "mercy", "compassion", config)

        note, _deck_id = mw.col.added[0]
        self.assertEqual(note["Word"], "mercy")
        self.assertEqual(note["Plain Word"], "mercy")
        self.assertEqual(note["Sentence 1"], "Knowledge needs mercy.")
        self.assertEqual(note["Plain Sentence 1"], "Knowledge needs mercy.")
        self.assertEqual(note["Sentence 1 Translation"], "Knowledge requires mercy.")
        self.assertEqual(note["Sentence 2"], "Mercy needs knowledge.")
        self.assertEqual(note["Plain Sentence 2"], "Mercy needs knowledge.")
        self.assertEqual(note["Sentence 2 Translation"], "Mercy requires knowledge.")

    def test_favorites_export_uses_dedicated_deck_and_skips_duplicate_sentences(self):
        mw = self._mw()
        existing = FakeNote(mw.col.favorite_notetype)
        existing.id = 77
        existing["Sentence"] = "Schon da."
        mw.col.notes[77] = existing
        mw.col.search_results = [77]

        result = export_favorites_to_anki(
            mw,
            [
                {"text": "Schon da.", "translation": "Already there."},
                {
                    "text": "Der Hund schläft.",
                    "translation": "The dog sleeps.",
                    "target_words": [{"word": "Hund", "definition": "dog"}],
                },
            ],
        )

        self.assertEqual((result.added, result.skipped), (1, 1))
        note, deck_id = mw.col.added[0]
        self.assertEqual(deck_id, 99)
        self.assertEqual(note["Sentence"], "Der Hund schläft.")
        self.assertEqual(note["Target Words"], "<b>Hund</b>: dog")
        self.assertEqual(mw.col.undo_labels, ["Export Contextual Review Favorites"])


if __name__ == "__main__":
    unittest.main()
