# Research behind the add-on

Benjamin Paddags, Daniel Hershcovich, and Valkyrie Savage (2024).
**Automated Sentence Generation for a Spaced Repetition Software.**
Proceedings of the 19th Workshop on Innovative Use of NLP for Building Educational Applications, pages 351–364.

[Publisher page and citation](https://aclanthology.org/2024.bea-1.29/) · [Original paper](Paddags-Hershcovich-Savage-2024.pdf)

The PDF is unchanged; its filename now identifies the authors and year. The paper is distributed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Credit belongs to its authors; this independent add-on is not their software or an endorsed implementation.

## What we try to recreate

AllAI combines several due vocabulary items in a sentence and schedules the words individually. This add-on implements the retrieval idea: select suitable sentences from a local library and use them to practise Anki vocabulary in context.

| Study system | This add-on |
| --- | --- |
| Retrieval, generation, and hybrid conditions | Local sentence retrieval; no LLM sentence generation |
| Modified SM-2 scheduling | Native Anki scheduling, including FSRS |
| AllAI study interface | Anki recognition and recall, audio, favorites, and word mining |

The extra features are practical adaptations, not interventions validated by this paper.

## What the evidence supports

The ten-day study used a convenience sample of 26 Danish learners. Sentence-based conditions showed roughly fourfold vocabulary-learning efficiency relative to the single-word baseline, which also included an example sentence. After adjustment for multiple comparisons, the retrieval-versus-baseline efficiency difference remained significant. Some other reported differences did not survive that correction.

The small sample and short duration limit what can be concluded about lasting learning or other languages and learners. Results describe AllAI, not a trial of this add-on. Context and varied examples are useful practice opportunities; faster learning here is not established.

For personal practice, try producing an expression before revealing it, say the complete sentence aloud, and check whether you can use it in conversation or understand it on first listen. These suggestions are not the study protocol.
