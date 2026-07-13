# Contextual Spaced Repetition

Contextual Spaced Repetition is an Anki add-on that reviews due vocabulary in
sentences instead of one card at a time. It finds due cards, chooses an offline
sentence from a local SQLite corpus, lets you click the target words you forgot,
and grades the linked Anki cards through Anki's scheduler.

The add-on includes a tiny smoke-test corpus so the package can be tested, but
real use needs a sentence corpus for the language you are learning.

## Install

For local testing on Windows, double-click `sync_to_anki.bat` in this folder:

```text
sync_to_anki.bat
```

The batch file installs a tiny development loader into Anki's `addons21`
directory. Anki keeps using the code from this checkout:

```text
C:\path\to\contextual-spaced-repetition
```

That means new versions that arrive in this folder are picked up after
restarting Anki; you do not need to copy the full add-on into Anki every time.
The loader preserves Anki/user-owned state such as `meta.json`, `user_files/`,
`data/downloads/`, and existing SQLite databases. If an older install has a
legacy `data/contextual_sentences.db`, the loader setup copies it once to
`user_files/contextual_sentences.db` so the default settings keep finding it.

From PowerShell, the same setup is:

```powershell
python scripts/install_dev_loader.py
```

Use `--dry-run` to preview changes or `--no-clean` to leave old copied runtime
files in the installed add-on folder. The older full-copy updater remains
available as `python scripts/sync_to_anki.py` for packaged install testing.

To install the packaged build, install `dist/contextual_review_addon.ankiaddon`
from Anki's add-on screen.

## Quick Start Inside Anki

1. Open `Tools > Contextual Review > Settings`.
2. Choose the deck you want to configure.
3. Use `Preview Auto-Configure`, review the proposed changes, then apply them.
4. Choose what to study today.
5. Use the Sentence Library to import sentences.
6. Run `Diagnostics`, then start reviewing.

Custom sentence files, word-form imports, and full database maintenance remain
available under Advanced / Nerd Settings.

The add-on does not create a deck or edit your notes. Opening it, changing
settings, and importing sentences do not schedule cards. Existing cards are
scheduled only when you submit a contextual review with `Grade & Next`.

Japanese and Chinese sentences use script-aware matching so target expressions
can be found inside sentences that do not separate words with spaces.

## How To Review

In the review window, read the sentence and focus on the highlighted target
words. Click only the target words you did not remember. Leave words you knew
unclicked.

Use `Read sentence` to hear the current sentence with an online Microsoft Edge
voice. Audio is requested only when you press the button. Generated clips are
cached for quick replay, removed after seven days, and limited to 100 MB.

Use `Show Solution` to reveal the stored sentence translation and the
configured text, image, or audio fields for each matched card. Use `Grade & Next`
to grade the linked Anki cards and move to the next sentence.

Use the star button in the top-right corner to save or remove the current
sentence from favorites. Open `Tools > Contextual Review > Favorite Sentences`
to revisit saved sentences, translations, and target-word definitions later.
The list is filtered to the active language deck and its sentence database.

Clicked target cards are answered as `Again`. Unclicked target cards are
answered as `Good`. The add-on schedules those linked cards as a contextual
batch, so a sentence can cover multiple due words without being limited to
Anki's next queued card. `Ctrl+Z` restores the previous contextual batch.
Sentences are avoided while the current Contextual Review window remains open,
and recently shown sentences are also avoided when you close and reopen the
window. They can still appear again if matching due cards remain and the corpus
has limited alternatives.

Keyboard shortcuts:

- `Space` or `Enter`: show the solution, then submit on the next press.
- `1` to `9`: toggle the first nine target words.
- `Ctrl+Z`: undo the last contextual review and return to its sentence.

## Where To Get Sentence Files

The easiest path is inside Anki:

```text
Tools > Contextual Review > Settings > Sentence Library > Import More
```

Enter the language code suggested by the dialog, or use another Tatoeba code.
The add-on streams the official weekly per-language export from:

```text
https://downloads.tatoeba.org/exports/per_language/
```

By default, it imports up to 100,000 accepted sentences and does not keep the
compressed download cache. This keeps the SQLite review database much smaller
than a full uncapped corpus. Set `Max imported sentences` to `0` only when you
intentionally want to import everything; large languages can create databases
hundreds of MB in size.

When `Target language` and `Native language` differ in Settings, the downloader
also uses Tatoeba's offline links export to fill the sentence `translation`
column with a linked native-language sentence when one is available.
If a sentence has no stored translation, `Show Solution` offers a
`Translate Sentence` button that obtains a Google translation in the review window using
the bundled Python `deep-translator` client. Hover briefly over any non-target
word to see a cached quick translation without leaving the review window.

You can also import local files:

```text
Tools > Contextual Review > Settings > Advanced / Nerd Settings > Import Custom Sentence File
```

Supported sentence files:

- `.txt`: normal text or short text collections; the importer splits it into
  sentences.
- `.srt`: subtitle files.
- `.tsv` or `.csv`: sentence lists, optionally with IDs, language codes, or
  translations.
- `.bz2`: compressed Tatoeba-style TSV exports.

Good sources include subtitles, exported sentence lists, reading material you
have permission to use, and Tatoeba exports. A word list alone is not enough;
the add-on needs sentences.

Accepted table shapes include:

```text
Sentence text.
Sentence text.    Translation text.
42    Sentence text.
de    Satztext.
1     deu    Satztext.    Translation text.
```

Imported sentences are appended to the configured database path, which defaults
to:

```text
user_files/contextual_sentences.db
```

This location is preserved by Anki when the add-on is upgraded. If an older
configuration still points at the previous default
`data/contextual_sentences.db`, the add-on migrates that default path forward
to `user_files/contextual_sentences.db` when settings are loaded.

The compressed source file and the imported SQLite database are different sizes.
A `.bz2` Tatoeba archive may be only a few MB, while the expanded indexed
database can be much larger.

## Word Forms

Word-form files are optional. They help when your card has a base word but the
sentence contains an inflected or irregular form.

Use two columns: sentence form first, base card word second. TSV, CSV, and
plain `.txt` files with tab- or comma-separated columns are accepted.

```text
went    go
gone    go
going   go
Hunde   Hund
```

Import them inside Anki:

```text
Tools > Contextual Review > Settings > Advanced / Nerd Settings > Import Word Forms
```

`Lemma family` is the default because it lets one card match related forms.
`Exact word form` remains available in Advanced / Nerd Settings.

## Settings

Settings opens on `Basic Setup`. Most users only need to:

- `Choose a deck`: Settings opens with deck buttons. Pick the deck you want,
  and the saved settings apply to that deck and its subdecks.
- Use `Preview Auto-Configure` to detect target, translation, and audio fields.
  It reads the card templates and includes only directions where the target
  field appears on the question side. English-to-target production cards are
  excluded without requiring card numbers or Anki search syntax.
- Choose the language being learned.
- Map the target word, translation, and optional audio fields.
- Choose due cards, new cards with a separate maximum, and learning cards.
- Manage the sentence library. The dialog shows the existing language count,
  recommends 100,000 to 200,000 sentences, and supports importing more or
  deleting some or all.

`Advanced / Nerd Settings` contains Anki search syntax, card templates,
matching behavior, sentence lengths, database paths, dictionary URLs, import
filters, and additional solution fields. New profiles default to lemma-family
matching and sentences between 4 and 15 words.

Settings discovers note fields from the deck you chose and offers them in
editable dropdowns. Use `Refresh fields from selected deck` after changing
cards or note types in Anki.

Deck profiles are stored in the add-on config under `deck_configs`, but normal
setup should not require editing JSON by hand.

Use `Delete Entire Sentence Database` under Advanced / Nerd Settings to remove
the imported SQLite sentence database before creating or importing a replacement.
This does not delete or edit any Anki cards.

For a longer user-facing walkthrough, see
[docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## Build A Corpus Database From The Command Line

Inside Anki, the import buttons are usually easier. For development or release
builds, you can rebuild the bundled smoke corpus:

```powershell
python scripts/build_corpus.py --input data/seed_sentences.tsv --output data/contextual_sentences.db --language en --format tsv --word-forms data/seed_word_forms.tsv
```

The builder accepts plain text files and Tatoeba-style TSV. Review runtime does
not require spaCy. If spaCy is installed and `--spacy-model` is supplied, the
builder uses its lemmas during preprocessing; otherwise it uses the bundled
lightweight normalizer.

Sentence selection uses SQLite FTS5/BM25 to retrieve candidates, then ranks them
by matched due-card coverage, scheduling priority, BM25 score, and shorter
sentence length.

## Tests

```powershell
python -m unittest discover -s tests
python scripts/smoke_review_loop.py
```

## Package For Anki

Build an installable `.ankiaddon` after tests pass:

```powershell
python scripts/package_addon.py
```

On Windows, you can instead double-click:

```text
build_addon.bat
```

It runs the test suite and smoke review, creates the latest package, and opens
the `dist` folder with `contextual_review_addon.ankiaddon` selected. This is the
file to send to another user. It does not install or sync the development copy.

The packager validates required runtime files, rebuilds
`dist/contextual_review_addon`, excludes tests/development artifacts, includes
the `user_files/` placeholder, and writes `dist/contextual_review_addon.ankiaddon`.

Before publishing, walk through [docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md).
