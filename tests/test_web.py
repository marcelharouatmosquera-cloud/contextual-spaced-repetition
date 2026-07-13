from __future__ import annotations

import unittest

from contextual_review.types import ReviewTask, SolutionFieldValue, TargetWordDefinition, Token
from contextual_review.web import render_message_html, render_task_html


class WebTests(unittest.TestCase):
    def _task(self) -> ReviewTask:
        return ReviewTask(
            sentence_id=1,
            language="en",
            full_text="We review.",
            translation="We review.",
            tokens=[
                Token(text="We", lemma="we", is_word=True, is_target=False),
                Token(text=" ", lemma="", is_word=False, is_target=False),
                Token(text="review", lemma="review", is_word=True, is_target=True, card_ids=(10,)),
                Token(text=".", lemma="", is_word=False, is_target=False),
            ],
            card_ids_by_key={"review": [10]},
            target_words=(
                TargetWordDefinition(
                    card_id=10,
                    target_word="review",
                    definition="revise",
                    good_interval="12 days",
                    again_interval="today",
                ),
            ),
        )

    def test_render_task_contains_bridge_payload(self) -> None:
        html = render_task_html(self._task())

        self.assertIn("pycmd", html)
        self.assertIn("review", html)
        self.assertIn("Show Solution", html)
        self.assertIn("Grade &amp; Next", html)
        self.assertIn('id="submit" class="primary-action" type="button" disabled', html)
        self.assertIn("selection-summary", html)
        self.assertIn("Sentence Translation", html)
        self.assertIn("Target Words", html)
        self.assertIn("targetWords", html)
        self.assertIn("revise", html)
        self.assertIn("unknown_keys", html)
        self.assertIn("known_keys", html)
        self.assertIn("unknown_card_ids", html)
        self.assertIn("known_card_ids", html)
        self.assertIn('data-card-id="10"', html)
        self.assertIn("Good:", html)
        self.assertIn("12 days", html)
        self.assertIn("Again:", html)
        self.assertIn('id="speak-sentence"', html)
        self.assertIn("Read sentence", html)
        self.assertIn('action: "speak_sentence"', html)
        self.assertIn("contextualTtsFinished", html)

    def test_task_payload_escapes_script_end_tags(self) -> None:
        task = ReviewTask(
            sentence_id=3,
            language="en",
            full_text="We review.",
            translation='Bad </script><img src=x onerror="alert(1)">',
            tokens=[
                Token(text="review", lemma="review", is_word=True, is_target=True, card_ids=(10,)),
            ],
            card_ids_by_key={"review": [10]},
            target_words=(
                TargetWordDefinition(
                    card_id=10,
                    target_word="review",
                    definition="close </script> safely",
                ),
            ),
        )

        html = render_task_html(task)

        self.assertIn("<\\/script>", html)
        self.assertNotIn("</script><img", html)

    def test_target_words_are_keyboard_accessible_without_global_shortcut_bubbling(self) -> None:
        html = render_task_html(self._task())

        self.assertIn('span.setAttribute("role", "button")', html)
        self.assertIn("aria-pressed", html)
        self.assertIn("event.stopPropagation()", html)
        self.assertIn("isInteractiveShortcutTarget", html)

    def test_context_words_offer_debounced_hover_translation(self) -> None:
        html = render_task_html(self._task())

        self.assertIn('id="context-translation-tooltip"', html)
        self.assertIn('document.querySelectorAll(".word.context")', html)
        self.assertIn('action: "hover_translate"', html)
        self.assertIn("}, 180);", html)
        self.assertIn("window.contextualTranslationFinished", html)
        self.assertIn("contextTranslationCache", html)

    def test_ctrl_z_routes_to_contextual_undo(self) -> None:
        html = render_task_html(self._task())

        self.assertIn('event.key.toLowerCase() === "z"', html)
        self.assertIn('{ action: "undo" }', html)

    def test_favorite_button_is_small_and_fixed_in_the_top_right(self) -> None:
        html = render_task_html(self._task(), is_favorite=True)

        self.assertIn('id="favorite"', html)
        self.assertIn('aria-pressed="true"', html)
        self.assertIn('>&#x2605;</button>', html)
        self.assertIn('action: "toggle_favorite"', html)
        self.assertIn("window.contextualFavoriteChanged", html)
        self.assertIn("#favorite {\n  position: fixed;\n  top: 14px;\n  right: 14px;", html)

    def test_today_progress_is_number_free_and_anchored_after_actions(self) -> None:
        html = render_task_html(
            self._task(),
            progress_completed=3,
            progress_total=10,
            can_undo=True,
        )

        self.assertIn('aria-label="Today\'s review progress"', html)
        self.assertIn('style="--review-progress: 30.0000%"', html)
        self.assertNotIn("3 of 10 completed", html)
        self.assertNotIn("<progress", html)
        self.assertGreater(html.index('class="session-progress"'), html.index('class="actions"'))
        self.assertIn("position: fixed", html)
        self.assertIn("bottom: 0", html)
        self.assertIn('id="undo" class="compact-action"', html)
        self.assertIn('aria-label="Previous sentence"', html)
        self.assertIn('>&#x21B6;</button>', html)
        self.assertIn("#undo {\n  position: fixed;\n  top: 14px;\n  left: 14px;", html)
        self.assertNotIn('>&#x21B6; Previous</button>', html)
        self.assertNotIn('__UNDO_DISABLED__', html)

    def test_submit_is_guarded_against_duplicate_activation(self) -> None:
        html = render_task_html(self._task())

        self.assertIn("function submitAnswer()", html)
        self.assertIn("if (submit.disabled)", html)
        self.assertIn("submit.disabled = true", html)
        self.assertIn("function cardIdsForNodes(nodes)", html)

    def test_target_word_details_include_forgotten_toggle_buttons(self) -> None:
        html = render_task_html(self._task())

        self.assertIn('marker.className = "mark-unknown"', html)
        self.assertIn("toggleUnknownForCardId", html)
        self.assertIn('button.textContent = isUnknown ? "Marked forgotten" : "Mark forgotten"', html)
        self.assertIn("button.primary-action", html)

    def test_solution_fields_render_text_images_and_audio_safely(self) -> None:
        task = self._task()
        rich_task = ReviewTask(
            sentence_id=task.sentence_id,
            language=task.language,
            full_text=task.full_text,
            translation=task.translation,
            tokens=task.tokens,
            card_ids_by_key=task.card_ids_by_key,
            target_words=(
                TargetWordDefinition(
                    card_id=10,
                    target_word="review",
                    solution_fields=(
                        SolutionFieldValue("reading", "Reading", "text", text="review"),
                        SolutionFieldValue("picture", "Picture", "image", media=("image.jpg",)),
                        SolutionFieldValue(
                            "audio",
                            "Audio",
                            "audio",
                            media=("voice.mp3",),
                            autoplay=True,
                        ),
                    ),
                ),
            ),
        )

        html = render_task_html(rich_task)

        self.assertIn('"solutionFields"', html)
        self.assertIn("image.jpg", html)
        self.assertIn("voice.mp3", html)
        self.assertIn("function renderImages", html)
        self.assertIn("function renderAudio", html)
        self.assertIn("playAutoplayAudio", html)

    def test_lookup_can_enable_without_translation(self) -> None:
        html = render_task_html(
            ReviewTask(
                sentence_id=2,
                language="en",
                full_text="We go out.",
                translation=None,
                tokens=[
                    Token(text="We", lemma="we", is_word=True, is_target=False),
                    Token(text=" ", lemma="", is_word=False),
                    Token(
                        text="go",
                        lemma="go",
                        is_word=True,
                        is_target=True,
                        match_key="go",
                        lookup_text="go",
                        card_ids=(20,),
                    ),
                    Token(text=" out.", lemma="", is_word=False),
                ],
                card_ids_by_key={"go": [20]},
                target_words=(
                    TargetWordDefinition(card_id=20, target_word="go", definition="go out"),
                ),
            )
        )

        self.assertIn("No stored sentence translation.", html)
        self.assertIn("Translate Sentence", html)
        self.assertIn("translate_sentence", html)
        self.assertIn('translateSentence.textContent = "Translating…"', html)
        self.assertIn("translation.textContent = translatedText", html)
        self.assertIn("go out", html)
        self.assertIn("solution.hidden = false", html)
        self.assertIn("lookup.disabled = selectedUnknownTargets().length === 0", html)
        self.assertNotIn("lookup.disabled = translation.hidden", html)

    def test_message_can_render_multiple_action_buttons(self) -> None:
        html = render_message_html(
            "No matching sentence",
            "Run diagnostics or switch modes.",
            action_label="Diagnostics",
            action="diagnostics",
            extra_actions=(("Standard Reviews", "standard_review"),),
        )

        self.assertIn("Diagnostics", html)
        self.assertIn("diagnostics", html)
        self.assertIn("Standard Reviews", html)
        self.assertIn("standard_review", html)
        self.assertIn('data-action="diagnostics"', html)
        self.assertIn('data-action="standard_review"', html)
        self.assertIn("this.dataset.action", html)
        self.assertNotIn('action: "diagnostics"', html)

    def test_loading_message_can_hide_refresh_action(self) -> None:
        html = render_message_html(
            "Finding a sentence",
            "Searching locally.",
            show_refresh=False,
        )

        self.assertNotIn(">Refresh</button>", html)


if __name__ == "__main__":
    unittest.main()
