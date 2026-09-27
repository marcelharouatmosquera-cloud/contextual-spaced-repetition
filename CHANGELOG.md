# Release notes

## 1.1.0

- Bundle Snowball 3.0.1 for Arabic, Danish, Dutch, Finnish, French, Greek,
  Italian, Portuguese, Russian, Spanish, Swedish, and Turkish word families.
  Replace the hand-written Russian stemmer with the official implementation.
- Stem original spellings before folding accents, search existing sentence
  libraries without reimporting, and retain imported irregular word forms.
  Recheck visible words before assigning review cards.
- Explain matching coverage in Diagnostics, including missing built-in rules
  for Polish and Ukrainian. Stemming does not cover every inflection.
- Search 100 due cards per sentence instead of 20, giving the most urgent word
  more due companions to share a sentence with. Settings still at the old
  default of 20 are raised once; other values are kept.
- Keep accents in dictionary lookups, hover translations, and mined words, so
  *действительность* and *Mädchen* are no longer sent as *деиствительность*
  and *madchen*.
- Fall back to the MyMemory translation service while Google is rate-limiting
  requests.
- Include relearning cards that become due during a session in today's goal.
- Require Anki 25.07 or later, the first version with the scheduler call used
  for grading.
- Stop concurrent log writes from corrupting the troubleshooting log.

## 1.0.0

- Add a setup walkthrough directly to Basic Setup, with clear Auto-Configure and Save steps.
- Replace documentation screenshots with isolated examples showing recall, grading, and progress.
- Explain the research origins and limitations; include the original paper under its authors and year.
- Correct outdated safety and library instructions and separate developer utilities from installation.
- Keep deck overview launch controls outside the deck table.

### Features

- Start Contextual Review directly from Anki's deck list and deck overview.
- See the installed version, copy version information, and open downloads from
  the visible Version button or Tools menu.
- Report bugs through a short GitHub form with version details filled in.
- Includes the accumulated review, sentence-selection, translation, favorites,
  recent-sentence, and mined-word improvements since 0.1.1.

Install the `.ankiaddon` from the release assets through Anki's Tools > Add-ons >
Install from file, then restart Anki. Existing add-on configuration and files
under `user_files/` are preserved. A full sentence corpus is needed for real use;
the included corpus is a small test sample.
