from __future__ import annotations

import unittest
from types import SimpleNamespace

from contextual_review.auto_config import auto_config_summary, detect_deck_configuration


class FakeNote:
    def __init__(self, fields, templates, note_id=1) -> None:
        self.fields = dict(fields)
        self.templates = list(templates)
        self.id = note_id

    def keys(self):
        return list(self.fields)

    def __getitem__(self, key):
        return self.fields[key]

    def note_type(self):
        return {"name": "German Vocabulary", "tmpls": self.templates}


class FakeCard:
    def __init__(self, card_id, note, ordinal) -> None:
        self.id = card_id
        self._note = note
        self.ord = ordinal

    def note(self):
        return self._note


class FakeCollection:
    def __init__(self, cards) -> None:
        self.cards = {card.id: card for card in cards}

    def find_cards(self, query):
        return list(self.cards)

    def get_card(self, card_id):
        return self.cards[card_id]


class AutoConfigTests(unittest.TestCase):
    def test_detects_recognition_and_recall_card_templates(self) -> None:
        templates = [
            {"name": "Reading", "qfmt": "{{German}}", "afmt": "{{English}}"},
            {"name": "Production", "qfmt": "{{English}}", "afmt": "{{German}}"},
        ]
        first = FakeNote(
            {"German": "der Hund", "English": "the dog", "Audio": "[sound:hund.mp3]"},
            templates,
            1,
        )
        second = FakeNote(
            {"German": "das Haus", "English": "the house", "Audio": "[sound:haus.mp3]"},
            templates,
            2,
        )
        cards = [
            FakeCard(1, first, 0),
            FakeCard(2, first, 1),
            FakeCard(3, second, 0),
            FakeCard(4, second, 1),
        ]
        mw = SimpleNamespace(col=FakeCollection(cards))

        result = detect_deck_configuration(mw, "German", "de")

        self.assertTrue(result.confident)
        self.assertEqual(result.target_field, "German")
        self.assertEqual(result.translation_field, "English")
        self.assertEqual(result.audio_field, "Audio")
        self.assertEqual(result.included_templates, ("Reading",))
        self.assertEqual(result.recall_templates, ("Production",))
        self.assertEqual(result.included_card_count, 2)
        self.assertEqual(result.recall_card_count, 2)
        self.assertEqual(result.excluded_card_count, 0)
        summary = auto_config_summary(result, "German")
        self.assertIn("2 German to English recognition cards", summary)
        self.assertIn("2 English to German recall cards", summary)

    def test_generic_front_and_back_names_remain_safe(self) -> None:
        templates = [
            {"name": "Forward", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
            {"name": "Reverse", "qfmt": "{{Back}}", "afmt": "{{Front}}"},
        ]
        note = FakeNote({"Front": "der Hund", "Back": "the dog"}, templates)
        mw = SimpleNamespace(
            col=FakeCollection([FakeCard(1, note, 0), FakeCard(2, note, 1)])
        )

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="Front",
            preferred_translation_field="Back",
        )

        self.assertEqual(result.target_field, "Front")
        self.assertEqual(result.translation_field, "Back")
        self.assertEqual(result.included_templates, ("Forward",))
        self.assertEqual(result.recall_templates, ("Reverse",))

    def test_clean_matching_field_maps_to_visible_field_and_respects_hidden_css(self) -> None:
        templates = [
            {
                "name": "Card 1",
                "qfmt": (
                    '<div class="front">{{Word}}</div>'
                    '<div class="back hidden">{{Translation}}</div>'
                ),
                "afmt": "{{Translation}}",
            },
            {
                "name": "Card 2",
                "qfmt": (
                    '<div class="front hidden"><div>{{Word}}</div></div>'
                    '<div class="back">{{Translation}}</div>'
                ),
                "afmt": "{{Word}}",
            },
        ]
        note = FakeNote(
            {
                "Word": "собака",
                "Translation": "dog",
                "Sentence 1 Translation": "The dog is sleeping in the house.",
                "Plain Word": "собака",
                "Audio Word": "[sound:dog.mp3]",
            },
            templates,
        )
        mw = SimpleNamespace(
            col=FakeCollection([FakeCard(1, note, 0), FakeCard(2, note, 1)])
        )

        result = detect_deck_configuration(
            mw,
            "Russian Core 5000",
            "ru",
            preferred_target_field="Plain Word",
            preferred_translation_field="Translation",
        )

        self.assertTrue(result.confident)
        self.assertEqual(result.target_field, "Plain Word")
        self.assertEqual(result.translation_field, "Translation")
        self.assertEqual(result.audio_field, "Audio Word")
        self.assertEqual(result.included_templates, ("Card 1",))
        self.assertEqual(result.recall_templates, ("Card 2",))
        self.assertFalse(result.target_field_directly_on_question)

    def test_conditional_markers_do_not_make_target_field_visible(self) -> None:
        templates = [
            {
                "name": "Production",
                "qfmt": "{{#German}}{{English}}{{/German}}",
                "afmt": "{{German}}",
            }
        ]
        note = FakeNote({"German": "der Hund", "English": "the dog"}, templates)
        mw = SimpleNamespace(col=FakeCollection([FakeCard(1, note, 0)]))

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="German",
            preferred_translation_field="English",
        )

        self.assertTrue(result.confident)
        self.assertEqual(result.included_templates, ())
        self.assertEqual(result.recall_templates, ("Production",))
        self.assertEqual(result.recall_card_count, 1)

    def test_void_tag_inside_hidden_block_does_not_hide_later_translation(self) -> None:
        templates = [
            {
                "name": "Production",
                "qfmt": (
                    '<div style="display:none">{{German}}<br></div>'
                    "{{English}}"
                ),
                "afmt": "{{German}}",
            }
        ]
        note = FakeNote({"German": "der Hund", "English": "the dog"}, templates)
        mw = SimpleNamespace(col=FakeCollection([FakeCard(1, note, 0)]))

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="German",
            preferred_translation_field="English",
        )

        self.assertEqual(result.included_templates, ())
        self.assertEqual(result.recall_templates, ("Production",))

    def test_type_answer_filter_is_classified_as_recall(self) -> None:
        templates = [
            {
                "name": "Typed Answer",
                "qfmt": "{{English}}<br>{{type:German}}",
                "afmt": "{{German}}",
            }
        ]
        note = FakeNote({"German": "der Hund", "English": "the dog"}, templates)
        mw = SimpleNamespace(col=FakeCollection([FakeCard(1, note, 0)]))

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="German",
            preferred_translation_field="English",
        )

        self.assertEqual(result.included_templates, ())
        self.assertEqual(result.recall_templates, ("Typed Answer",))

    def test_visible_target_takes_precedence_when_both_fields_are_on_front(self) -> None:
        templates = [
            {
                "name": "Bilingual Front",
                "qfmt": "{{German}}<br>{{English}}",
                "afmt": "{{German}}",
            }
        ]
        note = FakeNote({"German": "der Hund", "English": "the dog"}, templates)
        mw = SimpleNamespace(col=FakeCollection([FakeCard(1, note, 0)]))

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="German",
            preferred_translation_field="English",
        )

        self.assertEqual(result.included_templates, ("Bilingual Front",))
        self.assertEqual(result.recall_templates, ())

    def test_main_note_type_translation_beats_small_front_back_note_type(self) -> None:
        german_templates = [
            {"name": "Card 2", "qfmt": "{{German}}", "afmt": "{{English}}"},
        ]
        basic_templates = [
            {"name": "Basic", "qfmt": "{{Front}}", "afmt": "{{Back}}"},
        ]
        cards = []
        for index in range(1, 41):
            note = FakeNote(
                {"German": "froh", "English": "glad, happy", "Audio": "[sound:froh.mp3]"},
                german_templates,
                index,
            )
            cards.append(FakeCard(index, note, 0))
        small_note = FakeNote({"Front": "hello", "Back": "hallo"}, basic_templates, 100)
        cards.append(FakeCard(100, small_note, 0))
        mw = SimpleNamespace(col=FakeCollection(cards))

        result = detect_deck_configuration(
            mw,
            "German",
            "de",
            preferred_target_field="Front",
            preferred_translation_field="Back",
        )

        self.assertEqual(result.target_field, "German")
        self.assertEqual(result.translation_field, "English")
        self.assertEqual(result.audio_field, "Audio")


if __name__ == "__main__":
    unittest.main()
