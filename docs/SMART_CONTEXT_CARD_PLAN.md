# Smart Context Card

Status: implemented. Keep this document as the safety and behavior reference.

## Goal

Let a learner create a vocabulary note from an unknown word in the current
context sentence without opening Anki's general Add window.

## Proposed flow

1. A hotkey or sentence action selects an unknown target-language word.
2. The active deck profile supplies the detected target and solution fields.
3. The selected word is written to the target field and its existing hover
   translation is written to the solution field.
4. The full context sentence is written to a detected example-sentence field
   when the note type has one.
5. Optional Edge TTS generates word audio and attaches it through Anki's media
   APIs. An Advanced / Nerd Settings toggle disables this behavior.
6. The new card is placed at the front of the new-card queue through Anki's
   supported collection/scheduler APIs.
7. An optional Nerd setting increases today's new-card allowance by the number
   of New cards the selected note type actually generated.

## Safety constraints

- Never insert or update Anki collection tables with SQL.
- Resolve the installed Anki version's supported note, media, scheduler, and
  deck-configuration APIs before implementation.
- Make creation one native undoable action and do not leave partial notes or
  orphaned audio when a later step fails.
- Detect duplicate notes before creation and let the learner choose whether to
  reuse, update, or create another note.
- Keep automatic audio and daily-limit changes opt-in and visible.
- Preserve the user's deck options. If a one-day limit adjustment is used,
  record exactly what changed and avoid turning it into a permanent deck-wide
  configuration change.

## Implementation checkpoints

1. Confirm field mapping and example-field detection across note types.
2. Prototype native note creation with undo and duplicate handling.
3. Add media generation with cleanup-on-failure tests.
4. Add native queue placement and verify it with Anki's actual scheduler state.
5. Add the optional one-day new-limit behavior only after verifying the current
   Anki backend API and its interaction with deck presets and subdecks.
6. Run an in-Anki acceptance test; unit tests alone cannot confirm scheduler UI
   order, sync behavior, or the effective daily limit.
