#!/usr/bin/env python
"""Build an SQLite FTS5 sentence corpus for the add-on."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from contextual_review.corpus import connect_database, insert_sentence, upsert_word_forms
from contextual_review.importer import (
    clean_sentence_text,
    read_paired_tatoeba_sentence_files,
    read_sentence_file,
    read_word_forms_file,
    sentence_quality_flags,
    sentence_word_map as lightweight_sentence_word_map,
)
from contextual_review.normalizer import count_words, normalize_form, normalize_word


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--language", default="en")
    parser.add_argument("--native-language", default="en")
    parser.add_argument("--format", choices=("auto", "plain", "tsv"), default="auto")
    parser.add_argument(
        "--native-input",
        type=Path,
        help="Optional native-language Tatoeba sentence export used to populate translations",
    )
    parser.add_argument(
        "--links-input",
        type=Path,
        help="Optional Tatoeba links.tar.bz2 or TSV links file used with --native-input",
    )
    parser.add_argument("--min-words", type=int, default=2)
    parser.add_argument("--max-words", type=int, default=10)
    parser.add_argument("--spacy-model", default="")
    parser.add_argument(
        "--word-forms",
        action="append",
        default=[],
        type=Path,
        help="Optional TSV/CSV file with form<TAB>base rows for query expansion",
    )
    parser.add_argument("--no-strict-filter", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.native_input) != bool(args.links_input):
        parser.error("--native-input and --links-input must be provided together")

    lemmatizer = _spacy_lemmatizer(args.spacy_model) if args.spacy_model else None
    working_output = _temporary_output_path(args.output)
    conn = connect_database(working_output)

    inserted = 0
    skipped = 0
    seen_texts = set()
    failed = False
    try:
        for language, text, translation in read_sentences(
            args.input,
            args.format,
            args.language,
            native_input=args.native_input,
            native_language=args.native_language,
            links_input=args.links_input,
        ):
            text = clean_sentence_text(text)
            translation = clean_sentence_text(translation) if translation else None
            dedupe_key = (language, text.casefold())
            if not text or dedupe_key in seen_texts:
                skipped += 1
                continue
            seen_texts.add(dedupe_key)

            words = count_words(text, language)
            if words < args.min_words or words > args.max_words:
                skipped += 1
                continue
            flags = sentence_quality_flags(text)
            if flags and not args.no_strict_filter:
                skipped += 1
                continue
            word_map = sentence_word_map(text, language, lemmatizer)
            if not word_map:
                skipped += 1
                continue
            insert_sentence(
                conn,
                language,
                text,
                translation,
                word_map,
                source=str(args.input),
                word_count=words,
                quality_flags=",".join(flags),
            )
            inserted += 1
        form_rows = 0
        for word_forms_path in args.word_forms:
            form_rows += import_word_forms(conn, word_forms_path)
        conn.commit()
    except Exception:
        failed = True
        raise
    finally:
        conn.close()
        if failed:
            working_output.unlink(missing_ok=True)

    backup_path = _backup_existing_output(args.output)
    working_output.replace(args.output)

    if args.word_forms:
        print(
            "Wrote %s sentences and %s word-form rows to %s (%s skipped)"
            % (inserted, form_rows, args.output, skipped)
        )
    else:
        print("Wrote %s sentences to %s (%s skipped)" % (inserted, args.output, skipped))
    if backup_path:
        print("Previous output backed up to %s" % backup_path)
    return 0


def read_sentences(
    path: Path,
    input_format: str,
    default_language: str,
    native_input: Optional[Path] = None,
    native_language: str = "en",
    links_input: Optional[Path] = None,
) -> Iterator[Tuple[str, str, Optional[str]]]:
    if native_input and links_input:
        yield from read_paired_tatoeba_sentence_files(
            path,
            default_language,
            native_input,
            native_language,
            links_input,
        )
        return
    yield from read_sentence_file(path, default_language, input_format=input_format)


def import_word_forms(conn, path: Path) -> int:
    rows = list(read_word_forms_file(path))
    upsert_word_forms(conn, rows)
    return len(rows)


def _temporary_output_path(output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1000):
        candidate = output_path.with_name(
            ".%s.build.%s.%s.tmp" % (output_path.name, os.getpid(), attempt)
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not create a temporary output path next to %s" % output_path)


def _backup_existing_output(output_path: Path) -> Optional[Path]:
    if not output_path.exists():
        return None
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for attempt in range(1000):
        suffix = ".bak-%s" % stamp if attempt == 0 else ".bak-%s-%s" % (stamp, attempt)
        backup_path = output_path.with_name(output_path.name + suffix)
        if not backup_path.exists():
            shutil.copy2(output_path, backup_path)
            return backup_path
    raise RuntimeError("Could not create a backup path for %s" % output_path)


def sentence_word_map(text: str, language: str, lemmatizer=None) -> Dict[str, str]:
    if lemmatizer is None:
        return lightweight_sentence_word_map(text, language)

    pairs = lemmatizer(text, language)
    word_map: Dict[str, str] = {}
    for word_form, lemma in pairs:
        if word_form and lemma:
            word_map[word_form] = lemma
    return word_map


def _spacy_lemmatizer(model_name: str):
    try:
        import spacy
    except Exception as exc:
        raise SystemExit("spaCy is not installed: %s" % exc)

    nlp = spacy.load(model_name, disable=["ner", "parser"])

    def lemmatize(text: str, language: str) -> List[Tuple[str, str]]:
        pairs: List[Tuple[str, str]] = []
        for token in nlp(text):
            if not token.is_alpha:
                continue
            word_form = normalize_form(token.text)
            lemma = normalize_word(token.lemma_, language)
            if word_form and lemma:
                pairs.append((word_form, lemma))
        return pairs

    return lemmatize


if __name__ == "__main__":
    raise SystemExit(main())
