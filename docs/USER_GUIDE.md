# Contextual Review user guide

## Install and start

Install the `.ankiaddon` from [GitHub Releases](https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition/releases/latest) through **Tools → Add-ons → Install from file**, then restart Anki. Use Anki Desktop 23.10 or later. Mobile Anki apps cannot run this add-on.

Select a vocabulary deck and open **Tools → Contextual Review → Settings**. The deck screen's **Start Contextual Review** button starts practice after setup. **Version** shows your installed version and download link.

## Simple setup

1. In Settings, select the vocabulary deck to configure.
2. Under **Basic Setup**, choose **Language you are learning** and **Language for translations**. Choose these yourself before running Auto-Configure.
3. Click **Preview Auto-Configure Fields**. Check the proposed word, translation, optional audio, and recognition/recall templates. Recognition shows the target-language word; recall asks you to produce it from a meaning hint.
4. Click **Yes** to apply the proposal to the settings editor. This does not save yet. Verify the fields shown in Step 3. If detection is wrong, select the correct fields manually; template mappings are under **Advanced / Nerd Settings**.
5. Leave new-card learning off initially if you want to practise due and learning cards only.
6. In **Sentence Library**, click **Import More** and import sentences for your learning language. The bundled sample is only for testing. Download size varies by language; the searchable library takes additional space.
7. Click **Save**. Run **Tools → Contextual Review → Diagnostics**, resolve missing fields or library warnings, then start a review.

Repeat the language and field checks for each deck with a different layout or language. The **Setup walkthrough / Quick Guide** button in Basic Setup explains these steps inside Anki.

![Basic Setup](images/setup.png)
![Auto-Configure proposal](images/auto-configure.png)

## Review a sentence

For recognition, try to understand the highlighted words in context. For recall, produce the missing target-language forms before revealing them. Click **Show Solution** or press Space/Enter.

![Recall question](images/recall-question.jpg)

After revealing, click each forgotten target word or its **Mark forgotten** button. Forgotten targets receive **Again**; the others receive **Good**. You can toggle a mistaken selection before submitting. Check the Again/Good count, then click **Grade & Next** or press Space/Enter. Anki determines each card's next interval.

![Answer with one forgotten word](images/recall-answer.jpg)

These screenshots use example cards and illustrative progress: 8 done, 3 learning, 20 total. Green shows completed work, orange learning, and gray remaining work. Learning cards can require further repetitions; the bar is not a measure of language proficiency.

Use the previous-sentence control (Ctrl+Z) to undo the previous contextual review when available. A new-card introduction uses **Start Learning**, which starts that card at Anki's first learning step; it is not graded as remembered just because you saw the answer.

## Sentences, audio, and useful extras

Hover over a non-target word to see its automatic translation. Move into the popup, choose **Add Note**, check or edit **Word** and **Meaning**, then choose **Create Note** or **Cancel**. An exact match can be reused instead of duplicated.

The star saves a favorite sentence. The history button opens your last 100 sentences. Favorites can be exported as Anki notes. Word lookup and the add-note flow let you turn useful unfamiliar vocabulary into notes; existing matching notes may be reused. Review proposed fields before adding.

For recall, sentence audio becomes available after revealing the solution; recognition can play it before reveal. Existing audio fields depend on your deck configuration. Sentence selection works locally; library downloads need internet. Automatic translation sends requested text to Google, while generated sentence and mined-word audio use Microsoft's online Edge TTS. Cached translations and audio can be reused offline.

Advanced settings contain custom sentence and word-form imports, template mapping, and technical controls. Most users can begin with Basic Setup. A larger relevant library improves the chance of varied sentences; repeated examples can occur when few sentences match your due words.

## What changes in Anki

Review answers and Start Learning change card scheduling. The add-on uses native Anki scheduling, including FSRS. Opening Settings or revealing a solution alone does not grade a card. Adding vocabulary and exporting favorites can create or reuse notes. Keep Anki's normal backups enabled.

## If something looks wrong

| Problem | What to check |
| --- | --- |
| No review work | Selected deck, due/learning cards, and whether new-card learning is enabled |
| No suitable sentences | Import a library for the selected language and run Diagnostics |
| Wrong word or meaning | Recheck language choices and Auto-Configure fields, then Save |
| Recall appears as recognition | Verify card-template mappings in Advanced settings |
| Translation or audio unavailable | Internet connection, language choices, and configured audio field |
| Changes do not appear | Save settings; restart Anki after installing an update |

For a bug, use **Report a bug** on the deck screen or Tools menu. The public GitHub form includes the add-on, Anki, and OS versions automatically when opened from the add-on. Add a short title, what you did, what happened, and what you expected. Remove personal details from screenshots. A GitHub account is required.

## Practice advice and research

Try saying the complete expression aloud after checking it. Notice whether you can use it in a casual reply, recover after hesitation, and understand a short example before reading. Card accuracy alone does not establish those skills.

This is an independent adaptation of Paddags, Hershcovich, and Savage's 2024 AllAI research. Read the [research notes and paper](research/README.md) for the source, differences, and study limitations.
