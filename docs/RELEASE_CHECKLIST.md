# Release Checklist

Use this before publishing a build to AnkiWeb.

## Local Verification

- Run `python -m unittest discover -s tests`.
- Run `python scripts/smoke_review_loop.py`.
- Run `python -m compileall contextual_review scripts tests`.
- Rebuild the smoke corpus with `python scripts/build_corpus.py --input data/seed_sentences.tsv --output data/contextual_sentences.db --language en --format tsv --word-forms data/seed_word_forms.tsv`.
- Build the package with `python scripts/package_addon.py`.
- On Windows, `build_addon.bat` may be used to run the tests, smoke review, and packaging steps together.
- Confirm `dist/contextual_review_addon.ankiaddon` exists.

## Package Contents

- `manifest.json`, `config.json`, and root `__init__.py` are present at the zip root.
- `contextual_review/` contains only runtime Python modules.
- `README.md`, `docs/USER_GUIDE.md`, and `docs/RELEASE_CHECKLIST.md` are included.
- `data/contextual_sentences.db` and `data/language_profiles.json` are included.
- `user_files/README.txt` is included, but user-created files under `user_files/` are not bundled.
- Development folders such as `tests/`, `.git/`, and `IMPORTANT-Development instructions/` are not included.
- Download caches under `data/downloads/` are not included.

## Manual Anki Smoke Test

- Install the `.ankiaddon` into a clean Anki profile on a supported Qt6 build.
- Open `Tools > Contextual Review > Settings`, save settings, and restart the review window.
- Confirm target and solution field dropdowns discover fields from the selected deck.
- Add, remove, reorder, and relabel solution fields; verify text, image, and audio display modes.
- Confirm an audio field can be played manually and that auto-play triggers at most one audio item when the solution opens.
- With Learn New Cards disabled, mine a word and confirm the success banner, `mined-word` tag, native undo label, and one-card contextual introduction after grading the current sentence. Repeat with automatic New-limit increase enabled and confirm Anki still shows `Undo Add Contextual Note`, then undo and verify the note disappears. Confirm the introduction cannot be marked Good/Again, says `Start Learning`, and places only that exact card at Anki's first learning step through Again.
- Mine another word with Learn New Cards disabled, close the review window before grading, reopen Contextual Review, and confirm recognition is recovered first. After starting it, confirm the masked recall sibling is also recovered, is separated by two unrelated sentences when available, and is still shown at session end when no other work exists.
- Confirm the Tools menu contains only Start Review, Favorite Sentences, Settings, Quick Guide, and Diagnostics.
- Confirm Basic Setup contains auto-configuration and the Sentence Library without requiring a separate setup wizard.
- Confirm custom sentence import, word-form import, and full database deletion remain available in Advanced / Nerd Settings.
- Open `Tools > Contextual Review > Quick Guide` and confirm it explains deck safety, sentence sources, optional word forms, and how to review by clicking forgotten target words.
- Open `Tools > Contextual Review > Diagnostics` and confirm scheduler, undo checkpoint, due search, and corpus checks are OK or expected.
- Open the add-on from Anki's Add-ons screen and confirm the Config action opens the custom settings dialog if the Anki build supports custom config actions.
- Import a small `.txt` or `.tsv` corpus and verify the progress dialog updates.
- Import a small word-forms TSV and confirm diagnostics reports word-form mappings.
- Confirm Settings opens on Basic Setup and Advanced / Nerd Settings contains technical controls.
- Confirm Auto-Configure detects target and translation fields, maps target-to-native templates to recognition, and maps native-to-target templates to recall.
- Confirm the Basic field mapping discovers target, translation, and optional audio fields.
- Confirm the Due, New with maximum, and Learning card choices affect card collection.
- Confirm the Sentence Library shows the language count, imports toward a selected target, and can delete some or all sentences for that language.
- In Advanced / Nerd Settings, confirm the separate Recognition and Recall template lists route cards correctly and the Front-only option applies only to recognition cards.
- Start `Tools > Contextual Review > Start Review` on a deck with due cards.
- Set `Vocabulary matching` to `Lemma family` and confirm a seeded form such as `went -> go` can grade the `go` card.
- Import Japanese text containing `。` without spaces and confirm sentences split, import, match, and highlight an embedded target expression.
- On a recall card, confirm the exact inflected target form is replaced by its native-language hint, the sentence translation is visible before reveal, and TTS is blocked.
- With automatic TTS enabled, wait briefly on a recall question, reveal it, and confirm the prepared audio plays immediately without having played before reveal.
- Reveal the solution with Space/Enter and confirm the blank becomes the target form and Target Words definitions are shown.
- Toggle the favorite star, restart Anki, and confirm Favorite Sentences still shows the saved sentence and allows removal.
- For a sentence without a stored translation, confirm translation starts automatically, carries an automatic-translation warning, and hovering a non-target word shows a quick tooltip translation.
- Mark one target word as unknown, press Next, and confirm the matched card receives `Again`.
- Leave one target word unmarked, press Next, and confirm the matched card receives `Good`.
- Confirm the displayed Again/Good times match Anki's native answer-button labels for a New, Learning, and Review card.
- On a forward/reverse note with sibling burying disabled, confirm the reverse card is separated by two unrelated sentences when available and is still shown when it is the only due work.
- With two due words sharing a corpus sentence, confirm the greedy selector finds the two-word sentence even when many shorter one-word candidates exist.
- Use Anki undo immediately after a sentence and confirm the batch answer is reversible.
- Press Ctrl+Z while the next sentence is still being found and confirm the previous batch and progress bar are restored.
- Confirm an unavailable/missing card surfaces an error before any review answer is applied.
- Temporarily point the database path at a missing file and confirm Start Review tells the user to use the setup wizard, Tatoeba download, or sentence import.
- Test dark mode and light mode.

## Known Release Risks

- Full Anki runtime behavior still needs manual QA because the unit tests use fakes.
- The bundled corpus is only a smoke-test database; users should import a real corpus.
- Lemma-family matching depends on `word_forms` coverage. Exact-form matching remains available for stricter decks.
