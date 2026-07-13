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
- Confirm the Tools menu contains only Start Review, Favorite Sentences, Settings, Quick Guide, and Diagnostics.
- Confirm Basic Setup contains auto-configuration and the Sentence Library without requiring a separate setup wizard.
- Confirm custom sentence import, word-form import, and full database deletion remain available in Advanced / Nerd Settings.
- Open `Tools > Contextual Review > Quick Guide` and confirm it explains deck safety, sentence sources, optional word forms, and how to review by clicking forgotten target words.
- Open `Tools > Contextual Review > Diagnostics` and confirm scheduler, undo checkpoint, due search, and corpus checks are OK or expected.
- Open the add-on from Anki's Add-ons screen and confirm the Config action opens the custom settings dialog if the Anki build supports custom config actions.
- Import a small `.txt` or `.tsv` corpus and verify the progress dialog updates.
- Import a small word-forms TSV and confirm diagnostics reports word-form mappings.
- Confirm Settings opens on Basic Setup and Advanced / Nerd Settings contains technical controls.
- Confirm Auto-Configure detects target and translation fields, selects the reading card template by name, and excludes the reverse template.
- Confirm the Basic field mapping discovers target, translation, and optional audio fields.
- Confirm the Due, New with maximum, and Learning card choices affect card collection.
- Confirm the Sentence Library shows the language count, imports toward a selected target, and can delete some or all sentences for that language.
- In Advanced / Nerd Settings, confirm Included card templates can limit review to one direction and the Front-only option skips reverse cards.
- Start `Tools > Contextual Review > Start Review` on a deck with due cards.
- Set `Vocabulary matching` to `Lemma family` and confirm a seeded form such as `went -> go` can grade the `go` card.
- Import Japanese text containing `。` without spaces and confirm sentences split, import, match, and highlight an embedded target expression.
- Reveal the solution with Space/Enter and confirm it shows the sentence translation plus Target Words definitions.
- Toggle the favorite star, restart Anki, and confirm Favorite Sentences still shows the saved sentence and allows removal.
- For a sentence without a stored translation, confirm `Translate Sentence` returns a Google translation in the window and hovering a non-target word shows a quick tooltip translation.
- Mark one target word as unknown, press Next, and confirm the matched card receives `Again`.
- Leave one target word unmarked, press Next, and confirm the matched card receives `Good`.
- Use Anki undo immediately after a sentence and confirm the batch answer is reversible.
- Confirm an unavailable/missing card surfaces an error before any review answer is applied.
- Temporarily point the database path at a missing file and confirm Start Review tells the user to use the setup wizard, Tatoeba download, or sentence import.
- Test dark mode and light mode.

## Known Release Risks

- Full Anki runtime behavior still needs manual QA because the unit tests use fakes.
- The bundled corpus is only a smoke-test database; users should import a real corpus.
- Lemma-family matching depends on `word_forms` coverage. Exact-form matching remains available for stricter decks.
