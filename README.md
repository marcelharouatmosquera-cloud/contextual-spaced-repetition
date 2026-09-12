# Contextual Spaced Repetition

### Practise your Anki vocabulary in changing sentences.

[Download for Anki](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/releases/latest) · [User guide](docs/USER_GUIDE.md) · [Report a bug](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/issues/new?template=bug_report.yml)

This is an independent attempt to bring the **sentence-based spaced repetition**
approach studied by **Benjamin Paddags, Daniel Hershcovich, and Valkyrie Savage**
at the University of Copenhagen into Anki. Their 2024 paper,
[*Automated Sentence Generation for a Spaced Repetition Software*](https://aclanthology.org/2024.bea-1.29/),
introduced **AllAI**: practise several due words in a sentence while scheduling
each word separately.

This add-on follows the paper's sentence-retrieval approach. It finds examples
in a local library, turns your vocabulary cards into recognition or recall
exercises, and sends your answers to Anki. **Anki keeps scheduling each card
independently**, using your learning steps and scheduler, including FSRS.

![Recall exercise with two missing words and a visible session progress bar.](docs/images/recall-question.jpg)

*Example data rendered with the add-on's actual review interface. Produce the
missing words before revealing. The bar shows 8 done, 3 learning, and 20 total;
these are illustrative values, not study results.*

## What the add-on actually does

Contextual Review is an alternative review window for your existing Anki
vocabulary cards. You select a deck, map its word and meaning fields, and import
a sentence library. When you start, the add-on looks for sentences containing
vocabulary from the cards eligible for review. One sentence can exercise several
targets, and you assess each target separately.

For example, if **trinken** and **Kaffee** are due, you might practise both in
*Wir trinken morgens Kaffee.* Remembering trinken and forgetting Kaffee gives
their linked cards different answers. Other words in the sentence provide context;
merely seeing them does not automatically add them to your deck or grade them.

The next example is selected from the library rather than permanently attached
to the card. Available examples, sentence-length settings, and the due vocabulary
all affect what you see. A small or poorly matched library can produce repetition
or leave words without a suitable example.

Your notes remain your vocabulary source. This is not an automatic conversion
of the deck into sentence notes: the contextual exercise is assembled when you
review. Anki still records the linked cards' answers and determines their next
intervals. You can also continue to use Anki's normal reviewer.

## Two ways to learn: recognition and recall

The direction comes from your **card templates**, not a random choice during
review. Auto-Configure proposes the mappings; you can inspect or change them in
**Advanced / Nerd Settings → Card Selection**.

| | Recognition: target language → meaning | Recall: meaning → target language |
| --- | --- | --- |
| Typical original card | German word on the front, English meaning on the back | English meaning on the front, German word on the back |
| Contextual question | Target words remain visible in a sentence | Target words are replaced by blanks containing meaning hints |
| Example | Wir **trinken** morgens **Kaffee**. | Wir **[ to drink ]** morgens **[ coffee ]**. |
| Your task | Understand the highlighted words in this context | Produce the missing target-language words before revealing |
| After reveal | Check meanings and mark forgotten targets | Compare your answer with the revealed sentence forms and mark misses |

**Recognition** practises understanding a word when you encounter it. Attempt
the meaning before showing the solution; recognising the translation afterwards
is not the same as remembering it beforehand.

**Recall** is a contextual, cloze-style exercise for your reverse cards. Hints
come from the card's configured meaning fields, and the sentence translation
is shown when available. English is only an example: use your chosen translation
language. Say or think of the missing word; there is no typed-answer or automatic
speech-grading requirement. You judge your answer after reveal. The revealed
answer is the form used in that sentence, which may be an inflection of the word
on your vocabulary note.

You do **not** need to change the note type to Anki's Cloze type. You do need
actual reverse cards and a usable meaning field: assigning a template to Recall
does not create missing reverse cards. In Advanced settings, put the forward
card template under **Recognition templates** and the reverse template under
**Recall templates**. A recall-only setup is possible by configuring recall
templates and leaving recognition templates empty. Make sure the Anki search
query does not exclude the reverse cards.

Recognition and recall use separate sentence tasks, so a visible recognition
target does not give away a recall blank in the same task. When both directions
of a note are due, recognition is selected first; recall remains subject to the
queue and Anki's sibling settings. Each direction keeps its own card schedule.

**Audio respects the exercise:** automatic sentence reading can play recognition
sentences immediately. Recall sentence audio waits until **Show Solution**, so it
does not speak the missing answers before you try.

### How this differs from the paper

The AllAI study's interface asked learners to interpret a visible sentence,
reveal its translation, and mark words they did not remember (section 4.1).
**Our meaning-to-target cloze-style recall mode is an adaptation added for Anki's
reverse cards; it was not the exercise evaluated in that study.** The paper does
mention earlier cloze-question research in its related work (section 2.2), so it
would be inaccurate to say it never mentions cloze exercises. Its reported
results do not establish the effectiveness of this added recall mode.
[Read the original paper](https://aclanthology.org/2024.bea-1.29/).

## Why practise this way?

- **Context:** see a word's meaning and inflected form in a complete sentence.
- **Several targets, separate schedules:** a suitable sentence can review more
  than one due word, with individual Again/Good answers.
- **Variety:** changing examples help you practise beyond one familiar card.
  Sentences can repeat when the library has few suitable alternatives.
- **Two directions:** understand visible words on recognition cards; produce
  missing target-language forms on recall cards.

The study reported roughly four times greater vocabulary-learning efficiency
in its sentence-based groups than its single-word baseline, which also showed
an example sentence. It involved **26 Danish learners over ten days**. These
promising short-term findings concern AllAI, **not a measured result for this
add-on or a guarantee of faster learning**. Read the
[research notes and original PDF](docs/research/README.md) for the limitations
and differences from the study.

## Install

1. Use [Anki Desktop](https://apps.ankiweb.net/), version 23.10 or later.
2. Download **contextual_review_addon.ankiaddon** from the
   [latest release](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/releases/latest).
   Choose this asset, rather than GitHub's source-code ZIP.
3. Open **Tools → Add-ons → Install from file**, select the download, and restart Anki.

You need a vocabulary deck and a sentence library in its language. The bundled
library is a tiny test sample. This desktop add-on does not run in AnkiDroid or
AnkiMobile. Live checks have used Windows with Anki 25.09.4; other platforms have
not had a live acceptance test.

**Updates:** install the newer `.ankiaddon` the same way and restart. Add-on
settings and files under `user_files/` are preserved.

## Simple setup: Auto-Configure first

**Choose a deck → choose both languages → preview and apply → verify fields → import sentences → save.**

1. Select your vocabulary deck. Open **Tools → Contextual Review → Settings**
   and click the deck you want to configure.
2. In **Basic Setup**, choose **Language you are learning** and **Language for
   translations**. Auto-Configure does not choose the languages for you.
3. Click **Preview Auto-Configure Fields**. Read the preview: the target field
   should contain the word being learned, the translation field its meaning,
   and recognition/recall templates should match the two card directions.
4. Click **Yes** to apply the proposal to the editor. Verify the suggested
   fields in Step 3. Audio is optional. If the proposal is wrong, choose No and
   set the fields yourself; check the template lists in Advanced settings.

![Basic Setup showing language choices, Auto-Configure, and suggested fields.](docs/images/setup.png)

*An isolated example deck. Your field names may differ: Word/Meaning, Front/Back,
Expression/Definition, and language-named fields are all possible.*

![The actual Auto-Configure preview for the example deck.](docs/images/auto-configure.png)

*Check which fields and card directions were detected, then confirm. Applying
this preview changes the editor; **Save** commits the settings.*

5. Keep **Review Due Cards** and **Include Learning/Red Cards** enabled. Add new
   cards gradually once you are comfortable with the review flow.
6. In **Sentence Library**, choose a **Library size** and click **Import More**.
   We recommend 150,000–200,000 sentences as a starting library. Coverage and
   example variety depend on your deck and language; this is a practical
   recommendation, not a scientific threshold. Time and disk usage vary.
7. Click **Save**. Run **Tools → Contextual Review → Diagnostics** and address
   errors, then click **Start Contextual Review** on the deck screen.

For another language deck, repeat setup for that deck. Most users can leave
Advanced settings alone. The [user guide](docs/USER_GUIDE.md) explains custom
sentence imports, word forms, and troubleshooting.

## Review in four steps

| Step | What to do |
| --- | --- |
| **Try** | Understand the visible target on recognition cards. For recall, say or think of the missing word before revealing. |
| **Reveal** | Click **Show Solution** or press **Space**. Check the answer, meaning, and available audio. |
| **Mark misses** | Click only targets you **did not remember**, or use **Mark forgotten**. Leave remembered targets unmarked. |
| **Continue** | Press **Grade & Next**. Marked targets receive **Again**; unmarked targets receive **Good**. |

![Revealed answer with one forgotten target, one remembered target, and visible progress.](docs/images/recall-answer.jpg)

*Example: Kaffee is marked forgotten and will receive Again; trinken is left
unmarked and will receive Good. The shown intervals are illustrative; your
intervals come from Anki.*

**Accidental answer?** Press **Ctrl+Z immediately** to undo the previous
contextual batch. Opening a review or revealing its solution does not grade cards.

The progress bar shows **green = finished for today**, **orange = learning or
relearning later today**, and **gray = remaining work from the initial session
goal**. “Nothing due right now” may mean a learning step is still waiting.

## New cards, word mining, favorites, and history

**Due and learning cards:** Basic Setup lets you choose due reviews, learning
cards, and optionally new cards. Learning cards can return for another step;
a sentence being finished does not necessarily mean every card is done for today.

**Learn New Cards:** enable this in Basic Setup when you want to include new
vocabulary, and set the maximum. Leave it off to concentrate on existing reviews.

**Pick up vocabulary from a sentence:** hover over a non-target word for a
translation. Pause over the word, then move into the popup to use its controls.
If it is useful, choose **Add Note**, edit the **Word** and **Meaning** if needed,
then click **Create Note**. Use **Cancel** to leave without creating anything.
The add-on uses the deck's note type and includes sentence context in the new
note. An exact matching note can be reused and its New cards moved to the front
instead of creating a duplicate. This is an explicit action, not automatic mining
of every unfamiliar word. Optional mined-note audio and an increase to today's
New limit are available in Nerd Settings.

**Newly mined cards have an introduction:** the add-on can bring a mined card
into the contextual flow even with general new-card learning disabled. Its
introduction uses **Start Learning** instead of claiming you already remembered
it. This starts that card at Anki's first learning step through Again. Where the
note has both directions, recognition is introduced before recall.

**Keep useful sentences:** click the star to save a favorite. Open Favorite
Sentences to revisit them or export them as Anki notes. The clock opens the last
100 sentences, useful for returning to an example you just saw. Browsing history
is separate from undoing a review answer.

### Small controls worth knowing

| Control | What it does |
| --- | --- |
| **Hover over a non-target word** | Shows an automatic word translation and the **Add Note** action. This is for context words; highlighted review targets use the reveal/mark workflow. Translation may take a moment or fail if the online service is unavailable. |
| **Mark forgotten / Marked forgotten** | Toggles that target's answer. Click again to correct a mistaken selection before grading. The summary shows how many linked cards will receive Again and Good. |
| **Look Up** | Opens dictionary lookup for targets you marked forgotten. It becomes available when at least one target is marked. The dictionary address is configurable in Nerd Settings. |
| **Read sentence** | Plays the sentence using an online voice. Recall waits until reveal; deck audio fields are separate and can also be played after revealing. |
| **Retry Translation** | Appears when automatic sentence translation fails, so you can try again without grading the sentence. Machine translations can contain mistakes. |
| **Star** | Toggles whether the current sentence is a favorite. In **Favorite Sentences**, select an entry to see its details, remove it, or use **Export All to Anki Deck**; export skips duplicates. |
| **Clock / Last 100 Sentences** | Opens recent examples so you can inspect them again. This does not roll back scheduling. |
| **Previous sentence / Ctrl+Z** | Undoes the previous contextual review batch when available. For note creation, use Anki's **Undo Add Contextual Note** action; it is a separate operation. |
| **Space or Enter** | Reveals the solution, then grades and continues. Buttons and text fields keep their own keyboard behavior when focused. |
| **1–9** | Activates the corresponding target in sentence order. Revealed targets can be toggled forgotten/remembered; hidden recall answers stay protected until reveal. |
| **Version / Report a bug** | Shows and copies your installed version, opens downloads, or opens a bug form with version details filled in. |

See the [user guide](docs/USER_GUIDE.md#sentences-audio-and-useful-extras) for
more about these tools.

## Advanced / Nerd Settings: what you can customize

Open **Tools → Contextual Review → Settings**, select a deck, then choose the
**Advanced / Nerd Settings** tab. Basic Setup is enough to begin; this tab lets
you adapt the review to unusual decks or your preferred practice style.
Settings apply to the selected deck and its subdecks. You can copy settings
from another deck, then check the language and field names before saving.

| Area | Controls and when they help |
| --- | --- |
| **Card Selection** | Set an Anki search query, recognition and recall template lists, the recognition front-field check, future-due window, and maximum cards per search. Use this to select a subset or fix reverse-card routing. Including future-due cards allows early practice. |
| **Vocabulary Matching** | Choose **Lemma family** to match related word forms using available language rules and mappings, or **Exact word form** for stricter matching. Lemma matching is not a guarantee that every inflection is understood. |
| **Sentence Matching** | Set the shortest and longest sentence, choose whether to ignore common words, use every word, or extract only the first word, and supply extra ignored words. Shorter sentences can make practice more manageable. |
| **Additional fields after Show Solution** | Add and reorder extra note fields, select text/image/audio display, customize labels, and choose audio behavior. Useful for pronunciation, pictures, or usage notes already in your deck. |
| **Storage and Advanced Options** | Choose the sentence database and dictionary URL, import filtering, whether to keep downloaded archives, mined-note audio, today's New-limit increase for mined cards, and sentence text size. |
| **Import and Maintenance** | Import a custom sentence file or word-form mappings, or delete the sentence database. Database deletion removes the sentence library; it is not a reset of your vocabulary deck. |

The option labelled **Only use verified sentences** applies automatic quality
filters during import; it does not mean every sentence has been checked by a
teacher. Review imported examples and automatic translations critically.

After changing settings, click **Save**. If cards disappear from the contextual
queue or the wrong direction appears, check the search query, template mappings,
and fields, then run **Diagnostics**.

## My practical suggestion

Begin with a small, familiar deck and a short session. Make an honest attempt
before revealing; recognising an answer only after seeing it is a miss. If
sentences feel overwhelming, use simpler material or a shorter sentence range.

After reveal, say one useful sentence aloud and change a detail to make it your
own. Mine selectively: choose expressions you expect to use, so the new-card
queue remains manageable. Pair this with real listening, reading, and conversation.

Once a week, check something beyond card accuracy:

- Can you give a few casual replies using the expressions you studied?
- Do you hesitate less and recover more easily when you forget a word?
- Can you understand a short example on the first listen, before reading it?

These are practice suggestions, not a protocol validated in the AllAI study.

## Online features and help

Sentence selection uses your local library and needs no LLM API key. Library
downloads need internet. Automatic translation sends the requested text to
Google; sentence audio and mined-word audio use Microsoft's online Edge TTS.
Stored translations and cached audio remain useful offline.

Click **Report a bug** on the deck screen or in the Tools menu. The GitHub form
fills in the add-on, Anki, and OS versions; add a title and describe the problem.
A GitHub account is required. Reports are public, so remove personal information
from screenshots and text. The **Version** button shows your installed version,
copies version information, and opens downloads.

---

Building or contributing? See the [developer guide](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/blob/main/developer/README.md).
