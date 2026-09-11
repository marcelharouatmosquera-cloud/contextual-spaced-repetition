# Contextual Spaced Repetition

**Version 1.0.0** · [Download](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/releases/latest) · [Report a bug](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/issues/new?template=bug_report.yml)

Contextual Spaced Repetition is an Anki add-on that reviews due vocabulary in
sentences instead of one card at a time. It finds due cards, chooses an offline
sentence from a local SQLite corpus, lets you click the target words you forgot,
and grades the linked Anki cards through Anki's scheduler.

The add-on includes a tiny smoke-test corpus so the package can be tested, but
real use needs a sentence corpus for the language you are learning.

## Start and get help

Click **Start Contextual Review** on Anki's deck list or the deck overview
(the screen with Study Now). The same action is under
`Tools > Contextual Review > Start Review`.

The **Version 1.0.0** button opens version information, a copy button, and the
latest download page. **Report a bug** opens a short GitHub form with the add-on,
Anki, and operating-system versions already filled in. Describe what went wrong;
screenshots and error messages are optional. Review the form and submit it using
a GitHub account. Nothing is posted automatically.

Reports appear in this repository's [Issues](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/issues).
Only version information is included automatically, never cards, deck contents,
configuration, or API keys. Reports are public, so remove private information
from any text or screenshots you attach.

## Install

Download `contextual_review_addon.ankiaddon` from the
[latest GitHub release](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/releases/latest).
In Anki, open `Tools > Add-ons`, choose `Install from file`, and select the
downloaded file. Restart Anki when installation finishes.

## Update

Download the newer `.ankiaddon` file from the Releases page and install it the
same way. Anki replaces the add-on code while keeping your add-on configuration,
downloaded sentence corpus, favorites, and other files stored under
`user_files/`.

For local development on Windows, double-click `sync_to_anki.bat` in this
folder:

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

To build a package yourself, run `python scripts/package_addon.py`, then install
`dist/contextual_review_addon.ankiaddon` from Anki's add-on screen.

### Publishing a new version

After testing and pushing changes to `main`, create and push a version tag:

```powershell
git tag v1.0.0
git push origin v1.0.0
```

The GitHub release workflow runs the tests and smoke review, builds the
`.ankiaddon` package, creates a matching Release, and attaches the package as a
download. Use a new version number for every release.

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

Contextual Review uses the direction of each configured card template:

- Recognition cards show the target-language word in the sentence as before.
- Recall cards replace the matched, inflected word with a `[ translation ]`
  blank and show the stored sentence translation on the question side. Say or
  think of the missing target-language form, then press `Space` or `Enter`.

`Show Solution` reveals every recall blank. Click only the revealed or
highlighted target words you did not remember; leave words you knew unclicked.

Use `Read sentence` to hear the current sentence with an online Microsoft Edge
voice. On recall questions, sentence audio remains unavailable until the answer
is revealed so it cannot give away the missing word. Generated clips are cached
for quick replay, removed after seven days, and limited to 100 MB.

Use `Show Solution` to reveal the stored sentence translation and the
configured text, image, or audio fields for each matched card. Use `Grade & Next`
to grade the linked Anki cards and move to the next sentence.

Use the star button in the top-right corner to save or remove the current
sentence from favorites. Open `Tools > Contextual Review > Favorite Sentences`
to revisit saved sentences, translations, and target-word definitions later.
The list is filtered to the active language deck and its sentence database.
`Export All to Anki Deck` copies them into a dedicated Contextual Review
Favorites deck and skips duplicate sentences.

Hover over a non-target word to translate it, then choose `Add Note` to mine it
into the current deck. The note uses the exact note type of the active card, so
note types with forward and reverse templates generate both cards. The detected
target, translation, example-sentence, and audio fields are filled when present;
the generated New cards are moved to the front through Anki's scheduler API.
Automatic word audio is enabled by default and can be disabled in Advanced /
Nerd Settings. The same tab has an optional `Increase today's New limit for
mined cards` switch. When enabled, it adds one temporary New-card slot per card
Anki actually generates, so a forward-and-reverse note normally adds two.
Every mined note is tagged `mined-word`. If `Learn New Cards` is disabled, the
add-on queues only the newly mined card for its own contextual sentence after
the current sentence is graded; it does not open the rest of the New queue.
That immediate follow-up is an introduction rather than a pass/fail review:
reveal the meaning and choose `Start Learning`. The add-on answers only that
exact card as Again through Anki, placing it at its first learning step. Later
appearances use the normal Again/Good controls. Pending mined introductions are
recovered from the `mined-word` tag and New-card state after the review window
or Anki is restarted. Recognition is introduced first; a New recall sibling is
then introduced separately after two unrelated sentences when other work is
available, or at the end of the session rather than being stranded.
A visible success banner confirms the word and card count and explains Ctrl+Z.

Clicked target cards are answered as `Again`. Unclicked target cards are
answered as `Good`. The add-on schedules those linked cards as a contextual
batch, so a sentence can cover multiple due words without being limited to
Anki's next queued card. It probes for sentences containing the urgent anchor
plus another due word before falling back to an ordinary one-word match. The
displayed Again/Good times come directly from Anki's scheduling states instead
of an estimated interval. Forward and reverse siblings from the same note are
kept at least two unrelated sentences apart when other work is available; a
sibling is never stranded when it is the only due card. `Ctrl+Z` restores the
previous contextual batch.
While the next sentence is being selected, the current sentence remains on
screen and Ctrl+Z stays available. The stacked progress bar updates immediately
after grading or undoing: green is finished for today, orange is waiting in an
intraday learning/relearning step, and gray is remaining from the session's
initial due-card goal.
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
If a sentence has no stored translation, the add-on obtains one automatically
with the bundled Python `deep-translator` client and labels it as automatically
translated. Hover briefly over any non-target word to see a cached quick
translation without leaving the review window.

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
  It reads the question side of each card template, mapping target-to-native
  templates to recognition and native-to-target templates to contextual recall.
- Choose the language being learned.
- Map the target word, translation, and optional audio fields.
- Choose due cards, new cards with a separate maximum, and learning cards.
- Manage the sentence library. The dialog shows the existing language count,
  recommends 100,000 to 200,000 sentences, and supports importing more or
  deleting some or all.

`Advanced / Nerd Settings` contains Anki search syntax, separate recognition
and recall template lists, matching behavior, sentence lengths, database paths,
dictionary URLs, import filters, and additional solution fields. New profiles
default to lemma-family matching and sentences between 4 and 12 words.

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

Sentence selection anchors the query on an urgent due word (intraday learning,
then overdue review, then normal review). It prefers sentences covering more
currently due cards before considering the total number of matched cards,
including optional early reviews. Nearer future reviews contribute more urgency
than distant ones, and a multi-word card contributes urgency only once.
Stored translations, BM25, and sentence length break the remaining ties.

Sentence length and already-shown examples are filtered before the search result
limit, so unusable top hits do not hide valid examples deeper in the corpus.
This applies to both spaced-word and Japanese/Chinese/Korean search paths.
Currently due companion words are searched before optional future companions
can fill the candidate pool. Index matches are verified against the displayed
targets before ranking or grading, so stale index entries cannot credit a word
that is absent from the exercise.
These changes preserve independent Anki scheduling and the existing
show-solution, mark-forgotten, Grade & Next interaction.

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

The native-API-only blueprint for the proposed unknown-word card creator is in
[docs/SMART_CONTEXT_CARD_PLAN.md](docs/SMART_CONTEXT_CARD_PLAN.md). It is a
future plan, not an implemented feature.
