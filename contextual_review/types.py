"""Shared data objects."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SolutionFieldValue:
    field: str
    label: str
    display: str
    text: str = ""
    media: Tuple[str, ...] = ()
    autoplay: bool = False


@dataclass(frozen=True)
class DueCard:
    card_id: int
    target_word: str
    lemma: str
    definition: str = ""
    solution_fields: Tuple[SolutionFieldValue, ...] = ()
    word_form: str = ""
    match_key: str = ""
    interval: int = 0
    factor: int = 2500
    overdue: float = 0.0
    due_in_days: int = 0
    priority: float = 0.0


@dataclass(frozen=True)
class TargetWordDefinition:
    card_id: int
    target_word: str
    definition: str = ""
    solution_fields: Tuple[SolutionFieldValue, ...] = ()
    good_interval: str = ""
    again_interval: str = ""


@dataclass(frozen=True)
class Token:
    text: str
    lemma: str
    is_word: bool
    is_target: bool = False
    match_key: str = ""
    lookup_text: str = ""
    card_ids: Tuple[int, ...] = ()


@dataclass(frozen=True)
class SentenceCandidate:
    sentence_id: int
    language: str
    full_text: str
    translation: Optional[str]
    matched_lemmas: List[str]
    score: float
    matched_card_count: int = 0
    bm25_score: float = 0.0
    word_count: int = 0


@dataclass(frozen=True)
class ReviewTask:
    sentence_id: int
    language: str
    full_text: str
    translation: Optional[str]
    tokens: List[Token]
    card_ids_by_key: Dict[str, List[int]]
    target_words: Tuple[TargetWordDefinition, ...] = ()
    matching_mode: str = "exact_form"
