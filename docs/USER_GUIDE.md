# Contextual Review User Guide

This guide is for using the add-on inside Anki.

## What You Need

You need two things:

1. Anki vocabulary cards with a field that contains the word you are learning.
2. A sentence corpus for the same language.

Word-form mappings are optional. They are useful when the card says `go` but
the sentence says `went`, or when a language has many inflected forms.

## Setup

Open:

```text
Tools > Contextual Review > Settings
```

Choose a deck, preview Auto-Configure, verify the detected fields, and use the
Sentence Library to add sentences. Then run Diagnostics and start reviewing.
Custom sentence and word-form imports are in Advanced / Nerd Settings.

The add-on does not create a new deck and does not edit your notes. Opening the
review window, changing settings, and importing sentences do not schedule
cards. Existing cards are scheduled only after you press `Grade & Next`.

## Settings

Set `Target note field` to the Anki note field containing the target-language
word. Common examples are `Front`, `Word`, `Expression`, `Vocabulary`, or the
name of the language.

Under `Fields shown after Show Solution`, add any note fields you want revealed
after answering. Each row can be shown as text, image, audio, or detected
automatically. You can add, remove, relabel, and reorder rows. Audio rows can
optionally play when the solution is revealed.

Field controls are populated from the deck you chose. If you change cards or
note types in Anki, click `Refresh fields from selected deck`.

Set `Target language` to a language code such as `en`, `de`, `es`, `fr`, `ru`,
or `ja`.

If you use Contextual Review with multiple language decks, open Settings,
choose the deck you want, and save that deck's language, fields, searches, and
database path. Choose the next language deck and repeat. Use `Copy settings
from...` if the new deck should start from an existing deck's setup. When you
later start reviews or imports, the add-on loads the profile for the active
deck automatically.

Basic Setup uses friendly choices for due cards, new cards, and learning cards.
`Preview Auto-Configure` detects field roles and card direction from note
fields and card templates. It keeps target-to-English reading cards and excludes
reverse English-to-target cards.
Open Advanced / Nerd Settings only when you need Anki search syntax or an
included card-template filter.

The default filter is:

```text
is:due -card:2 -card:3 -card:Reverse
```

The Sentence Library section shows how many sentences are already stored for
the selected language. A library of 100,000 to 200,000 sentences is recommended.
Choose a target size to import more, or delete a chosen amount or all sentences
for that language.

Deck profiles are stored in `deck_configs` in the add-on config, but normal
setup should not require editing JSON by hand. A profile for `Spanish` matches
`Spanish` and `Spanish::Subdeck` by default.

## Sentence Files

The easiest source is:

```text
Tools > Contextual Review > Settings > Sentence Library > Import More
```

The dialog suggests a language code from your settings. Accept it or enter a
Tatoeba code.

Tatoeba imports are capped by default. The add-on streams the compressed export,
imports up to `Max imported sentences`, and does not keep the compressed archive
unless `Keep downloaded archives` is enabled.

The compressed archive and the imported review database are different sizes. A
Tatoeba `.bz2` file may be only a few MB, while a full uncapped SQLite database
can grow to hundreds of MB.

To import your own material, use:

```text
Tools > Contextual Review > Settings > Advanced / Nerd Settings > Import Custom Sentence File
```

Supported files:

- `.txt`: normal text. The importer splits it into sentences.
- `.srt`: subtitle files.
- `.tsv` or `.csv`: sentence tables, optionally with IDs, language codes, or
  translations.
- `.bz2`: compressed Tatoeba-style TSV exports.

A word list is not enough. The add-on needs full sentences.

Accepted table shapes include:

```text
Sentence text.
Sentence text.    Translation text.
42    Sentence text.
de    Satztext.
1     deu    Satztext.    Translation text.
```

## Word-Form Files

Use word-form files only when you need morphology support. They are two-column
TSV, CSV, or text files. Text files may use tabs or commas between columns.

The first column is the form that may appear in a sentence. The second column is
the base word on your Anki card.

```text
went    go
eating  eat
Hunde   Hund
```

Import them with:

```text
Tools > Contextual Review > Settings > Advanced / Nerd Settings > Import Word Forms
```

Then set `Vocabulary matching` to `Lemma family` if you want those mappings to
affect review matching.

## Reviewing

Open:

```text
Tools > Contextual Review > Start Review
```

Read the sentence. Highlighted words are the target words linked to due Anki
cards.

Click only the target words you did not remember. Do not click words you knew.

Click `Show Solution` to reveal the stored sentence translation, the matched
card definitions, and the `Good`/`Again` interval preview. If no stored
sentence translation exists, use `Translate Sentence` to obtain a Google
translation directly in the review window. You can also hover briefly over a
non-target word for a quick translation.

Click `Grade & Next` to grade the sentence:

- Clicked target words are graded as `Again`.
- Unclicked target words are graded as `Good`.

Click the star in the top-right corner to save the current sentence. Favorite
Sentences in the Contextual Review tools menu lets you revisit saved sentences
for the active language deck and remove entries you no longer need.

You can also press `Space` or `Enter` to reveal the solution, then press it
again to submit. Number keys `1` to `9` toggle the first nine target words.
Press `Ctrl+Z` to undo the last contextual review and return to its sentence.

Contextual Review schedules the linked cards as a batch, so a sentence can
cover multiple due words without being limited to Anki's next queued card.
Sentences are avoided while the current Contextual Review window remains open,
and recently shown sentences are also avoided when you close and reopen the
window. They can still appear again if matching due cards remain and the corpus
has limited alternatives.

## Diagnostics

Run:

```text
Tools > Contextual Review > Diagnostics
```

Diagnostics checks the selected note fields, sentence database, scheduler API,
undo support, import support, word-form count, and whether the configured
search finds due cards.

After a contextual review, the add-on also writes a troubleshooting log to:

```text
user_files/contextual_review.log
```

The log records scheduler events, card IDs, answer ease, and before/after
scheduling fields. It does not include card text or note contents.

Fix diagnostics errors before using the add-on for real reviews.

## Example: Senren Japanese Notes

For the Senren fields `word`, `reading`, `definition`, `picture`, and
`wordAudio`, a useful starting configuration is:

- Target field: `word`
- Target language: `ja`
- Native language: `en`
- Solution fields: `reading` as text, `definition` as text
- Optional: `picture` as image and `wordAudio` as audio
- Settings deck: your Japanese deck

To exclude Senren audio-card and sentence-card modes while testing normal word
cards, use this Anki search:

```text
is:due -audioCard:_* -sentenceCard:_*
```

Japanese and Chinese use script-aware substring matching because they do not
normally separate every word with spaces.

## Removing Imported Sentences

Use:

```text
Tools > Contextual Review > Settings > Advanced / Nerd Settings > Delete Entire Sentence Database
```

This deletes only the add-on's imported sentence database. It does not delete,
move, or edit your Anki decks, notes, or cards.
