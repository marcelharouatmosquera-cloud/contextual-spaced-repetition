"""Corpus import/download helpers used by the Anki UI and scripts."""

from __future__ import annotations

import bz2
import csv
import io
import os
import re
import shutil
import sqlite3
import tarfile
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, IO, Iterable, Iterator, List, Optional, Sequence, Tuple

from .config import ContextConfig, addon_user_root, resolve_database_path
from .corpus import connect_database, insert_sentence, upsert_word_forms
from .language_profiles import normalize_language_code, profile_tatoeba_code
from .normalizer import count_words, normalize_form, tokenize_words

URL_RE = re.compile(r"https?://|www\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}", re.IGNORECASE)
IMPORT_BATCH_SIZE = 1000

ProgressCallback = Optional[Callable[[str, int], None]]

@dataclass(frozen=True)
class ImportResult:
    source: str
    database_path: Path
    inserted: int
    skipped: int
    limit: int = 0
    limit_reached: bool = False


def import_corpus_file(
    input_path: Path,
    config: ContextConfig,
    replace: bool = False,
    progress: ProgressCallback = None,
) -> ImportResult:
    return _import_sentence_rows(
        str(input_path),
        read_sentence_file(input_path, config.language),
        config,
        replace=replace,
        progress=progress,
    )


def _import_sentence_rows(
    source: str,
    rows: Iterable[Tuple[str, str, Optional[str]]],
    config: ContextConfig,
    replace: bool = False,
    progress: ProgressCallback = None,
) -> ImportResult:
    db_path = resolve_database_path(config)
    working_db_path = _replacement_database_path(db_path) if replace else db_path
    inserted = 0
    skipped = 0
    processed = 0
    limit = max(0, int(config.max_imported_sentences or 0))
    limit_reached = False
    seen_texts = set()
    conn = connect_database(working_db_path)
    failed = False
    try:
        for index, (language, text, translation) in enumerate(rows, start=1):
            processed = index
            text = clean_sentence_text(text)
            translation = clean_sentence_text(translation) if translation else None
            dedupe_key = (language, text.casefold())
            if not text or dedupe_key in seen_texts:
                skipped += 1
                continue
            seen_texts.add(dedupe_key)

            words = count_words(text, language)
            if words < config.min_sentence_words or words > config.max_sentence_words:
                skipped += 1
                continue
            flags = sentence_quality_flags(text)
            if flags and config.strict_import_filter:
                skipped += 1
                continue
            word_map = sentence_word_map(text, language)
            if not word_map:
                skipped += 1
                continue
            if conn.execute(
                "SELECT 1 FROM sentences WHERE language = ? AND full_text = ? LIMIT 1",
                (language, text),
            ).fetchone():
                skipped += 1
                continue
            inserted_id = insert_sentence(
                conn,
                language,
                text,
                translation,
                word_map,
                source=source,
                word_count=words,
                quality_flags=",".join(flags),
            )
            if inserted_id == 0:
                skipped += 1
                continue
            inserted += 1
            if inserted % 500 == 0:
                conn.commit()
                if progress:
                    progress(
                        "Scanned %s rows; imported %s sentences; skipped %s"
                        % (processed, inserted, skipped),
                        inserted,
                    )
            if limit and inserted >= limit:
                limit_reached = True
                if progress:
                    progress(
                        "Reached import limit of %s sentences after scanning %s rows"
                        % (limit, processed),
                        inserted,
                )
                break
        conn.commit()
    except Exception:
        failed = True
        raise
    finally:
        conn.close()
        if failed and replace:
            _remove_file_quietly(working_db_path)

    backup_path = None
    if replace:
        backup_path = _backup_existing_database(db_path)
        working_db_path.replace(db_path)

    if progress:
        if limit_reached:
            progress(
                "Finished: imported %s sentences; skipped %s; stopped at configured limit"
                % (inserted, skipped),
                inserted,
            )
        else:
            progress(
                "Finished: imported %s sentences; skipped %s" % (inserted, skipped),
                inserted,
            )
        if backup_path:
            progress("Previous database backed up to %s" % backup_path, inserted)
    return ImportResult(source, db_path, inserted, skipped, limit, limit_reached)


def import_word_forms_file(
    input_path: Path,
    config: ContextConfig,
    replace: bool = False,
    progress: ProgressCallback = None,
) -> ImportResult:
    db_path = resolve_database_path(config)
    inserted = 0
    skipped = 0
    conn = connect_database(db_path)
    try:
        if replace:
            conn.execute("DELETE FROM word_forms")
        batch: List[Tuple[str, str]] = []
        batch_seen = set()
        for index, (form, base) in enumerate(read_word_forms_file(input_path), start=1):
            if not form or not base:
                skipped += 1
                continue
            existing = conn.execute(
                "SELECT 1 FROM word_forms WHERE form = ? AND base = ? LIMIT 1",
                (form, base),
            ).fetchone()
            pair = (form, base)
            if existing or pair in batch_seen:
                skipped += 1
                continue
            batch.append(pair)
            batch_seen.add(pair)
            inserted += 1
            if len(batch) >= 1000:
                upsert_word_forms(conn, batch)
                batch.clear()
                batch_seen.clear()
                # A replacement must be all-or-nothing. For append imports,
                # periodic commits keep very large files practical.
                if not replace:
                    conn.commit()
                if progress:
                    progress("Scanned %s rows; imported %s word forms" % (index, inserted), inserted)
        if batch:
            upsert_word_forms(conn, batch)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if progress:
        progress("Finished: imported %s word forms; skipped %s" % (inserted, skipped), inserted)
    return ImportResult(str(input_path), db_path, inserted, skipped)


def download_tatoeba_sentences(
    language: str,
    config: ContextConfig,
    replace: bool = False,
    progress: ProgressCallback = None,
) -> ImportResult:
    code = tatoeba_code(language)
    url = tatoeba_sentences_url(code)
    native_code = tatoeba_code(config.native_language)

    if native_code and native_code != code:
        native_url = tatoeba_sentences_url(native_code)
        if progress:
            progress(
                "Streaming %s with %s translations from Tatoeba" % (url, native_code),
                0,
            )
        return _import_sentence_rows(
            url,
            read_paired_tatoeba_sentence_urls(
                url,
                config.language,
                native_url,
                config.native_language,
                progress=progress,
            ),
            config,
            replace=replace,
            progress=progress,
        )

    if not config.keep_downloaded_archives:
        if progress:
            limit = config.max_imported_sentences
            if limit:
                progress("Streaming %s and importing up to %s sentences" % (url, limit), 0)
            else:
                progress("Streaming and importing %s" % url, 0)
        return _import_sentence_rows(
            url,
            read_tatoeba_sentence_url(url, config.language),
            config,
            replace=replace,
            progress=progress,
        )

    download_dir = addon_user_root() / "data" / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    archive_path = download_dir / ("%s_sentences.tsv.bz2" % code)

    if progress:
        progress("Downloading %s" % url, 0)

    _download_file(url, archive_path, progress)

    if progress:
        progress("Importing %s" % archive_path.name, 0)
    return import_corpus_file(archive_path, config, replace=replace, progress=progress)


def tatoeba_code(language: str) -> str:
    language = (language or "en").strip().lower()
    if len(language) == 3:
        return language
    return profile_tatoeba_code(language)


def tatoeba_sentences_url(code: str) -> str:
    return "https://downloads.tatoeba.org/exports/per_language/%s/%s_sentences.tsv.bz2" % (
        code,
        code,
    )


def tatoeba_links_url() -> str:
    return "https://downloads.tatoeba.org/exports/links.tar.bz2"


def _download_file(url: str, output_path: Path, progress: ProgressCallback = None) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_sibling_path(output_path, "download")
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            downloaded = 0
            with temp_path.open("wb") as out:
                while True:
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if progress and (downloaded == len(chunk) or downloaded % (1024 * 1024) < len(chunk)):
                        if total:
                            progress(
                                "Downloaded %.1f MB of %.1f MB"
                                % (downloaded / 1048576.0, total / 1048576.0),
                                downloaded,
                            )
                        else:
                            progress("Downloaded %.1f MB" % (downloaded / 1048576.0), downloaded)
        temp_path.replace(output_path)
    except Exception:
        _remove_file_quietly(temp_path)
        raise


def read_sentence_file(
    path: Path, default_language: str, input_format: str = "auto"
) -> Iterator[Tuple[str, str, Optional[str]]]:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    resolved_format = input_format if input_format in {"auto", "plain", "tsv", "csv"} else "auto"

    if resolved_format == "plain":
        for sentence in _read_plain_sentences(path):
            yield _row_language(default_language), sentence, None
        return

    if resolved_format in {"tsv", "csv"}:
        delimiter = "\t" if resolved_format == "tsv" else ","
        for row in _read_delimited_rows(path, delimiter):
            parsed = parse_tsv_row(row, default_language)
            if parsed:
                yield parsed
        return

    if ".srt" in suffixes:
        for sentence in _read_srt_sentences(path):
            yield _row_language(default_language), sentence, None
        return

    if _looks_delimited(path, suffixes):
        delimiter = _delimiter_for(path, suffixes)
        for row in _read_delimited_rows(path, delimiter):
            parsed = parse_tsv_row(row, default_language)
            if parsed:
                yield parsed
        return

    for sentence in _read_plain_sentences(path):
        yield _row_language(default_language), sentence, None


def read_tatoeba_sentence_url(
    url: str, default_language: str
) -> Iterator[Tuple[str, str, Optional[str]]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        compressed = bz2.BZ2File(response, "rb")
        try:
            handle = io.TextIOWrapper(
                compressed,
                encoding="utf-8-sig",
                errors="replace",
                newline="",
            )
            try:
                reader = csv.reader(handle, delimiter="\t")
                for row in reader:
                    if not row:
                        continue
                    parsed = parse_tsv_row(row, default_language)
                    if parsed:
                        yield parsed
            finally:
                handle.detach()
        finally:
            compressed.close()


def read_paired_tatoeba_sentence_urls(
    target_url: str,
    target_language: str,
    native_url: str,
    native_language: str,
    links_url: Optional[str] = None,
    progress: ProgressCallback = None,
) -> Iterator[Tuple[str, str, Optional[str]]]:
    yield from pair_tatoeba_sentence_rows_streaming(
        read_tatoeba_sentence_id_rows_url(target_url, target_language),
        read_tatoeba_sentence_id_rows_url(native_url, native_language),
        read_tatoeba_links_url(links_url or tatoeba_links_url()),
        progress=progress,
    )


def read_paired_tatoeba_sentence_files(
    target_path: Path,
    target_language: str,
    native_path: Path,
    native_language: str,
    links_path: Path,
) -> Iterator[Tuple[str, str, Optional[str]]]:
    yield from pair_tatoeba_sentence_rows_streaming(
        read_tatoeba_sentence_id_rows_file(target_path, target_language),
        read_tatoeba_sentence_id_rows_file(native_path, native_language),
        read_tatoeba_links_file(links_path),
    )


def pair_tatoeba_sentence_rows_streaming(
    target_rows: Iterable[Tuple[int, str, str]],
    native_rows: Iterable[Tuple[int, str, str]],
    links: Iterable[Tuple[int, int]],
    progress: ProgressCallback = None,
) -> Iterator[Tuple[str, str, Optional[str]]]:
    with tempfile.TemporaryDirectory(prefix="contextual-review-tatoeba-") as tempdir:
        conn = sqlite3.connect(str(Path(tempdir) / "pairs.db"))
        try:
            _create_pairing_tables(conn)
            target_count = _load_pairing_target_rows(conn, target_rows)
            if progress:
                progress("Loaded %s target-language Tatoeba sentences" % target_count, target_count)

            link_count = _load_pairing_links(conn, links, progress=progress)
            linked_native_count = _pairing_linked_native_count(conn)
            if progress:
                progress(
                    "Found %s linked translation candidate(s)" % linked_native_count,
                    linked_native_count,
                )

            native_count = _load_pairing_native_rows(conn, native_rows)
            if progress:
                progress("Loaded %s native-language Tatoeba translations" % native_count, native_count)

            yield from _iter_paired_tatoeba_rows(conn)
        finally:
            conn.close()


def _create_pairing_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE target_rows (
          id INTEGER PRIMARY KEY,
          language TEXT NOT NULL,
          text TEXT NOT NULL,
          ordinal INTEGER NOT NULL
        );
        CREATE TABLE pairing_links (
          source_id INTEGER NOT NULL,
          translation_id INTEGER NOT NULL
        );
        CREATE UNIQUE INDEX idx_pairing_links_unique
          ON pairing_links(source_id, translation_id);
        CREATE INDEX idx_pairing_links_translation
          ON pairing_links(translation_id);
        CREATE TABLE native_rows (
          id INTEGER PRIMARY KEY,
          text TEXT NOT NULL
        );
        """
    )


def _load_pairing_target_rows(
    conn: sqlite3.Connection, target_rows: Iterable[Tuple[int, str, str]]
) -> int:
    batch: List[Tuple[int, str, str, int]] = []
    count = 0
    for ordinal, (sentence_id, language, text) in enumerate(target_rows, start=1):
        batch.append((int(sentence_id), str(language), str(text), ordinal))
        if len(batch) >= IMPORT_BATCH_SIZE:
            _insert_pairing_target_batch(conn, batch)
            count += len(batch)
            batch.clear()
    if batch:
        _insert_pairing_target_batch(conn, batch)
        count += len(batch)
    conn.commit()
    return count


def _insert_pairing_target_batch(
    conn: sqlite3.Connection, batch: Sequence[Tuple[int, str, str, int]]
) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO target_rows(id, language, text, ordinal) VALUES (?, ?, ?, ?)",
        batch,
    )


def _load_pairing_links(
    conn: sqlite3.Connection,
    links: Iterable[Tuple[int, int]],
    progress: ProgressCallback = None,
) -> int:
    batch: List[Tuple[int, int, int]] = []
    scanned = 0
    inserted = 0
    for scanned, (source_id, translation_id) in enumerate(links, start=1):
        source_id = int(source_id)
        translation_id = int(translation_id)
        batch.append((source_id, translation_id, source_id))
        if len(batch) >= IMPORT_BATCH_SIZE:
            inserted += _insert_pairing_link_batch(conn, batch)
            batch.clear()
            if progress and scanned % 500000 == 0:
                progress(
                    "Scanned %s Tatoeba links; kept %s target-language links"
                    % (scanned, inserted),
                    inserted,
                )
    if batch:
        inserted += _insert_pairing_link_batch(conn, batch)
    conn.commit()
    return inserted


def _insert_pairing_link_batch(
    conn: sqlite3.Connection, batch: Sequence[Tuple[int, int, int]]
) -> int:
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO pairing_links(source_id, translation_id)
        SELECT ?, ?
        WHERE EXISTS (SELECT 1 FROM target_rows WHERE id = ?)
        """,
        batch,
    )
    return conn.total_changes - before


def _pairing_linked_native_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(DISTINCT translation_id) FROM pairing_links").fetchone()
    return int(row[0] if row else 0)


def _load_pairing_native_rows(
    conn: sqlite3.Connection, native_rows: Iterable[Tuple[int, str, str]]
) -> int:
    batch: List[Tuple[int, str, int]] = []
    inserted = 0
    for sentence_id, _, text in native_rows:
        sentence_id = int(sentence_id)
        batch.append((sentence_id, str(text), sentence_id))
        if len(batch) >= IMPORT_BATCH_SIZE:
            inserted += _insert_pairing_native_batch(conn, batch)
            batch.clear()
    if batch:
        inserted += _insert_pairing_native_batch(conn, batch)
    conn.commit()
    return inserted


def _insert_pairing_native_batch(
    conn: sqlite3.Connection, batch: Sequence[Tuple[int, str, int]]
) -> int:
    before = conn.total_changes
    conn.executemany(
        """
        INSERT OR IGNORE INTO native_rows(id, text)
        SELECT ?, ?
        WHERE EXISTS (SELECT 1 FROM pairing_links WHERE translation_id = ?)
        """,
        batch,
    )
    return conn.total_changes - before


def _iter_paired_tatoeba_rows(conn: sqlite3.Connection) -> Iterator[Tuple[str, str, Optional[str]]]:
    rows = conn.execute(
        """
        SELECT
          t.language,
          t.text,
          (
            SELECT n.text
            FROM pairing_links l
            JOIN native_rows n ON n.id = l.translation_id
            WHERE l.source_id = t.id
            ORDER BY l.rowid
            LIMIT 1
          ) AS translation
        FROM target_rows t
        ORDER BY t.ordinal
        """
    )
    for language, text, translation in rows:
        yield str(language), str(text), str(translation) if translation is not None else None


def read_tatoeba_sentence_id_rows_url(
    url: str, default_language: str
) -> Iterator[Tuple[int, str, str]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        compressed = bz2.BZ2File(response, "rb")
        try:
            handle = io.TextIOWrapper(
                compressed,
                encoding="utf-8-sig",
                errors="replace",
                newline="",
            )
            try:
                yield from _read_tatoeba_sentence_id_rows(handle, default_language)
            finally:
                handle.detach()
        finally:
            compressed.close()


def read_tatoeba_sentence_id_rows_file(
    path: Path, default_language: str
) -> Iterator[Tuple[int, str, str]]:
    with _open_text(path) as handle:
        yield from _read_tatoeba_sentence_id_rows(handle, default_language)


def read_tatoeba_links_url(url: str) -> Iterator[Tuple[int, int]]:
    with urllib.request.urlopen(url, timeout=60) as response:
        yield from _read_tatoeba_links_tar(response)


def read_tatoeba_links_file(path: Path) -> Iterator[Tuple[int, int]]:
    suffix = "".join(path.suffixes).lower()
    if suffix.endswith(".tar.bz2"):
        with path.open("rb") as handle:
            yield from _read_tatoeba_links_tar(handle)
        return
    with _open_text(path) as handle:
        yield from _read_tatoeba_links(handle)


def read_word_forms_file(path: Path) -> Iterator[Tuple[str, str]]:
    suffixes = [suffix.lower() for suffix in path.suffixes]
    delimiter = _delimiter_for(path, suffixes)
    for row in _read_delimited_rows(path, delimiter):
        if not row or not any(part.strip() for part in row):
            continue
        if row[0].lstrip().startswith("#"):
            continue
        form = normalize_form(row[0])
        base = normalize_form(row[1] if len(row) > 1 else row[0])
        if form and base:
            yield form, base


def parse_tsv_row(parts: Sequence[str], default_language: str) -> Optional[Tuple[str, str, Optional[str]]]:
    parts = [part.strip() for part in parts]
    if not parts:
        return None
    if parts[0].isdigit():
        if len(parts) >= 3 and not _looks_language_code(parts[1], default_language):
            return _row_language(default_language), parts[1], parts[2] or None
        if len(parts) >= 3:
            return _row_language(parts[1] or default_language), parts[2], parts[3] if len(parts) >= 4 else None
        if len(parts) == 2:
            return _row_language(default_language), parts[1], None
        return None
    if _looks_language_code(parts[0], default_language) and len(parts) >= 2:
        return _row_language(parts[0]), parts[1], parts[2] if len(parts) >= 3 else None
    if len(parts) >= 2:
        return _row_language(default_language), parts[0], parts[1] or None
    return _row_language(default_language), parts[0], None


def parse_tatoeba_sentence_id_row(
    parts: Sequence[str], default_language: str
) -> Optional[Tuple[int, str, str]]:
    parts = [part.strip() for part in parts]
    if len(parts) < 3 or not parts[0].isdigit():
        return None
    return int(parts[0]), _row_language(parts[1] or default_language), parts[2]


def _read_tatoeba_sentence_id_rows(
    handle: IO[str], default_language: str
) -> Iterator[Tuple[int, str, str]]:
    reader = csv.reader(handle, delimiter="\t")
    for row in reader:
        parsed = parse_tatoeba_sentence_id_row(row, default_language)
        if parsed:
            yield parsed


def _read_tatoeba_links_tar(handle: IO[bytes]) -> Iterator[Tuple[int, int]]:
    with tarfile.open(fileobj=handle, mode="r|bz2") as archive:
        for member in archive:
            if not member.isfile():
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            for raw_line in extracted:
                line = raw_line.decode("utf-8-sig", errors="replace").strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                try:
                    yield int(parts[0]), int(parts[1])
                except Exception:
                    continue


def _read_tatoeba_links(handle: IO[str]) -> Iterator[Tuple[int, int]]:
    reader = csv.reader(handle, delimiter="\t")
    for row in reader:
        if len(row) < 2:
            continue
        try:
            yield int(row[0]), int(row[1])
        except Exception:
            continue


def _row_language(language: str) -> str:
    return normalize_language_code(language)


def _looks_language_code(value: str, default_language: str) -> bool:
    code = str(value or "").strip().lower()
    if not re.fullmatch(r"[a-z]{2,3}", code):
        return False
    expected = {str(default_language or "").strip().lower(), tatoeba_code(default_language)}
    return code in expected or code in _known_profile_codes()


@lru_cache(maxsize=1)
def _known_profile_codes() -> set[str]:
    try:
        from .language_profiles import load_language_profiles

        profiles = load_language_profiles()
    except Exception:
        return set()
    codes = set(profiles)
    for profile in profiles.values():
        if profile.tatoeba_code:
            codes.add(profile.tatoeba_code)
    return codes


def clean_sentence_text(text: Optional[str]) -> str:
    text = str(text or "")
    text = re.sub(r"\s+", " ", text.replace("\ufeff", " ")).strip()
    return text


def sentence_quality_flags(text: str) -> List[str]:
    flags: List[str] = []
    if not any(char.isalpha() for char in text):
        flags.append("no_letters")
    if URL_RE.search(text):
        flags.append("url_or_email")
    if re.search(r"([.!?])\1{2,}", text):
        flags.append("repeated_punctuation")
    if len(text) > 240:
        flags.append("too_long_chars")
    if any(len(token.text) > 35 for token in tokenize_words(text)):
        flags.append("oversized_token")
    if text.count("(") != text.count(")") or text.count("[") != text.count("]"):
        flags.append("unbalanced_brackets")
    if re.search(r"[{}<>|]", text):
        flags.append("markup_or_pipe")
    return flags


def sentence_word_map(text: str, language: str) -> Dict[str, str]:
    word_map: Dict[str, str] = {}
    for token in tokenize_words(text, language):
        word_form = normalize_form(token.text)
        lemma = token.lemma
        if word_form and lemma:
            word_map[word_form] = lemma
    return word_map


def _replacement_database_path(db_path: Path) -> Path:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return _temporary_sibling_path(db_path, "import")


def _temporary_sibling_path(path: Path, label: str) -> Path:
    path = path.resolve()
    stem = path.name
    for attempt in range(1000):
        candidate = path.with_name(
            ".%s.%s.%s.%s.tmp" % (stem, label, os.getpid(), attempt)
        )
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not create a temporary file path next to %s" % path)


def _backup_existing_database(db_path: Path) -> Optional[Path]:
    if not db_path.exists():
        return None
    backup_path = _backup_path(db_path)
    shutil.copy2(db_path, backup_path)
    return backup_path


def _backup_path(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for attempt in range(1000):
        suffix = ".bak-%s" % stamp if attempt == 0 else ".bak-%s-%s" % (stamp, attempt)
        candidate = path.with_name(path.name + suffix)
        if not candidate.exists():
            return candidate
    raise RuntimeError("Could not create a backup path for %s" % path)


def _remove_file_quietly(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


@contextmanager
def _open_text(path: Path) -> Iterator[IO[str]]:
    if path.suffix.lower() == ".bz2":
        handle = bz2.open(path, "rt", encoding="utf-8-sig", errors="replace", newline="")
    else:
        handle = path.open("rt", encoding="utf-8-sig", errors="replace", newline="")
    try:
        yield handle
    finally:
        handle.close()


def _looks_delimited(path: Path, suffixes: Sequence[str]) -> bool:
    if ".tsv" in suffixes or ".csv" in suffixes:
        return True
    sample = _read_sample(path)
    return "\t" in sample


def _delimiter_for(path: Path, suffixes: Sequence[str]) -> str:
    if ".tsv" in suffixes:
        return "\t"
    if ".csv" in suffixes:
        return ","
    return "\t" if "\t" in _read_sample(path) else ","


def _read_sample(path: Path, size: int = 4096) -> str:
    with _open_text(path) as handle:
        return handle.read(size)


def _read_delimited_rows(path: Path, delimiter: str) -> Iterator[List[str]]:
    with _open_text(path) as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for row in reader:
            if row:
                yield row


def _read_plain_sentences(path: Path) -> Iterator[str]:
    with _open_text(path) as handle:
        yield from _sentences_from_lines(handle)


def _read_srt_sentences(path: Path) -> Iterator[str]:
    def subtitle_lines() -> Iterator[str]:
        with _open_text(path) as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped or stripped.isdigit() or "-->" in stripped:
                    continue
                yield re.sub(r"<[^>]+>", "", stripped)

    yield from _sentences_from_lines(subtitle_lines())


def _sentences_from_lines(lines: Iterable[str]) -> Iterator[str]:
    pending = ""
    for line in lines:
        cleaned = line.replace("\r", " ").replace("\n", " ").strip()
        if not cleaned:
            continue
        pending = ("%s %s" % (pending, cleaned)).strip()
        while True:
            match = re.search(
                r"(?:(?<=[.!?])\s+|(?<=[\u3002\uff01\uff1f])(?:\s+|(?=\S)))",
                pending,
            )
            if not match:
                break
            sentence = pending[: match.end()].strip()
            if sentence:
                yield sentence
            pending = pending[match.end() :].lstrip()
    if pending.strip():
        yield pending.strip()
