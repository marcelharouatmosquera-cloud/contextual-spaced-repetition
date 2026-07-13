from __future__ import annotations

import bz2
import io
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from contextual_review.config import normalize_config
from contextual_review.importer import (
    _import_sentence_rows,
    import_corpus_file,
    import_word_forms_file,
    pair_tatoeba_sentence_rows_streaming,
    parse_tsv_row,
    read_paired_tatoeba_sentence_files,
    read_sentence_file,
    read_word_forms_file,
    sentence_quality_flags,
    tatoeba_code,
    tatoeba_links_url,
    tatoeba_sentences_url,
)


class ImporterTests(unittest.TestCase):
    def test_import_tsv_populates_word_forms(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.tsv"
            db_path = temp / "context.db"
            source.write_text("Students study daily.\\tStudents study daily.\\n", encoding="utf-8")
            config = normalize_config({"database_path": str(db_path), "language": "en"})

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("select base from word_forms where form = 'students'").fetchone()[0],
                    "student",
                )
            finally:
                conn.close()

    def test_japanese_sentence_import_uses_script_aware_length(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.txt"
            db_path = temp / "context.db"
            source.write_text("\u732b\u304c\u9b5a\u3092\u98df\u3079\u308b\u3002", encoding="utf-8")
            config = normalize_config(
                {
                    "database_path": str(db_path),
                    "language": "ja",
                    "min_sentence_words": 2,
                    "max_sentence_words": 10,
                }
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)

    def test_plain_japanese_text_splits_on_full_stop_without_spaces(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "sentences.txt"
            source.write_text(
                "\u732b\u304c\u9b5a\u3092\u98df\u3079\u308b\u3002\u72ac\u304c\u8d70\u3063\u3066\u3044\u308b\u3002",
                encoding="utf-8",
            )

            rows = list(read_sentence_file(source, "ja"))

            self.assertEqual(len(rows), 2)

    def test_tatoeba_url_uses_per_language_export(self) -> None:
        self.assertEqual(tatoeba_code("en"), "eng")
        self.assertEqual(
            tatoeba_sentences_url("eng"),
            "https://downloads.tatoeba.org/exports/per_language/eng/eng_sentences.tsv.bz2",
        )
        self.assertEqual(tatoeba_links_url(), "https://downloads.tatoeba.org/exports/links.tar.bz2")

    def test_read_paired_tatoeba_sentence_files_uses_links_tar(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            target = temp / "deu_sentences.tsv.bz2"
            native = temp / "eng_sentences.tsv.bz2"
            links = temp / "links.tar.bz2"
            with bz2.open(target, "wt", encoding="utf-8") as handle:
                handle.write("1\tdeu\tGute Beispiele helfen.\n")
            with bz2.open(native, "wt", encoding="utf-8") as handle:
                handle.write("10\teng\tGood examples help.\n")
            link_text = "1\t10\n10\t1\n".encode("utf-8")
            with tarfile.open(links, "w:bz2") as archive:
                info = tarfile.TarInfo("links.csv")
                info.size = len(link_text)
                archive.addfile(info, io.BytesIO(link_text))

            rows = list(read_paired_tatoeba_sentence_files(target, "de", native, "en", links))

            self.assertEqual(rows, [("de", "Gute Beispiele helfen.", "Good examples help.")])

    def test_import_word_forms_file_populates_query_expansion_table(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "forms.tsv"
            db_path = temp / "context.db"
            source.write_text("went\tgo\nrunning\trun\n# ignored\trow\n", encoding="utf-8")
            config = normalize_config({"database_path": str(db_path), "language": "en"})

            result = import_word_forms_file(source, config)

            self.assertEqual(result.inserted, 2)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("select base from word_forms where form = 'went'").fetchone()[0],
                    "go",
                )
            finally:
                conn.close()

    def test_read_word_forms_file_strips_punctuation_for_matching(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "forms.tsv"
            source.write_text("went,\tgo.\n", encoding="utf-8")

            self.assertEqual(list(read_word_forms_file(source)), [("went", "go")])

    def test_read_word_forms_txt_auto_detects_commas(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "forms.txt"
            source.write_text("went,go\nrunning,run\n", encoding="utf-8")

            self.assertEqual(list(read_word_forms_file(source)), [("went", "go"), ("running", "run")])

    def test_strict_import_filter_skips_urls_and_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.txt"
            db_path = temp / "context.db"
            source.write_text(
                "Gute Beispiele helfen. Gute Beispiele helfen. Mehr unter https://example.com.",
                encoding="utf-8",
            )
            config = normalize_config(
                {"database_path": str(db_path), "language": "de", "min_sentence_words": 2}
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            self.assertEqual(result.skipped, 2)

    def test_quality_flags_identify_markup(self) -> None:
        self.assertIn("markup_or_pipe", sentence_quality_flags("Bad <i>markup</i>."))

    def test_read_tsv_bz2_without_loading_archive_text_first(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "deu_sentences.tsv.bz2"
            with bz2.open(source, "wt", encoding="utf-8") as handle:
                handle.write("1\tdeu\tGute Beispiele helfen.\tGood examples help.\n")

            rows = list(read_sentence_file(source, "de"))

            self.assertEqual(rows, [("de", "Gute Beispiele helfen.", "Good examples help.")])

    def test_parse_common_sentence_table_shapes(self) -> None:
        self.assertEqual(parse_tsv_row(["42", "Short sentence."], "en"), ("en", "Short sentence.", None))
        self.assertEqual(
            parse_tsv_row(["42", "Good examples help.", "Buenos ejemplos ayudan."], "en"),
            ("en", "Good examples help.", "Buenos ejemplos ayudan."),
        )
        self.assertEqual(parse_tsv_row(["de", "Gute Beispiele helfen."], "en"), ("de", "Gute Beispiele helfen.", None))
        self.assertEqual(
            parse_tsv_row(["deu", "Gute Beispiele helfen.", "Good examples help."], "en"),
            ("de", "Gute Beispiele helfen.", "Good examples help."),
        )
        self.assertEqual(parse_tsv_row(["go", "ir"], "en"), ("en", "go", "ir"))

    def test_import_two_column_id_sentence_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.tsv"
            db_path = temp / "context.db"
            source.write_text("42\tGood examples help.\n", encoding="utf-8")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("select full_text from sentences").fetchone()[0],
                    "Good examples help.",
                )
            finally:
                conn.close()

    def test_import_three_column_id_sentence_translation_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.tsv"
            db_path = temp / "context.db"
            source.write_text("42\tGood examples help.\tBuenos ejemplos ayudan.\n", encoding="utf-8")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("select language, full_text, translation from sentences").fetchone(),
                    ("en", "Good examples help.", "Buenos ejemplos ayudan."),
                )
            finally:
                conn.close()

    def test_import_language_sentence_tsv_uses_row_language(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.tsv"
            db_path = temp / "context.db"
            source.write_text("de\tGute Beispiele helfen.\n", encoding="utf-8")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("select language, full_text from sentences").fetchone(),
                    ("de", "Gute Beispiele helfen."),
                )
            finally:
                conn.close()

    def test_import_corpus_respects_configured_sentence_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.tsv"
            db_path = temp / "context.db"
            source.write_text(
                "\n".join(
                    [
                        "One useful sentence.",
                        "Two useful sentences.",
                        "Three useful sentences.",
                    ]
                ),
                encoding="utf-8",
            )
            config = normalize_config(
                {
                    "database_path": str(db_path),
                    "language": "en",
                    "max_imported_sentences": 2,
                    "min_sentence_words": 2,
                }
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 2)
            self.assertTrue(result.limit_reached)
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(conn.execute("select count(*) from sentences").fetchone()[0], 2)
            finally:
                conn.close()

    def test_replace_import_keeps_old_database_if_rows_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            db_path = temp / "context.db"
            db_path.write_bytes(b"old database")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )

            def broken_rows():
                yield "en", "One useful sentence.", None
                raise RuntimeError("broken input")

            with self.assertRaisesRegex(RuntimeError, "broken input"):
                _import_sentence_rows("broken", broken_rows(), config, replace=True)

            self.assertEqual(db_path.read_bytes(), b"old database")
            self.assertFalse(list(temp.glob("*.tmp")))

    def test_replace_import_backs_up_previous_database_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.txt"
            db_path = temp / "context.db"
            source.write_text("One useful sentence.", encoding="utf-8")
            db_path.write_bytes(b"old database")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )

            result = import_corpus_file(source, config, replace=True)

            self.assertEqual(result.inserted, 1)
            backups = list(temp.glob("context.db.bak-*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"old database")
            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(conn.execute("select full_text from sentences").fetchone()[0], "One useful sentence.")
            finally:
                conn.close()

    def test_plain_text_import_reports_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "sentences.txt"
            db_path = temp / "context.db"
            source.write_text("One good sentence.\nTwo good sentences.", encoding="utf-8")
            config = normalize_config(
                {"database_path": str(db_path), "language": "en", "min_sentence_words": 2}
            )
            progress = []

            result = import_corpus_file(
                source,
                config,
                replace=True,
                progress=lambda message, value: progress.append((message, value)),
            )

            self.assertEqual(result.inserted, 2)
            self.assertTrue(progress)
            self.assertIn("Finished", progress[-1][0])

    def test_streaming_tatoeba_pairing_uses_first_available_translation(self) -> None:
        rows = list(
            pair_tatoeba_sentence_rows_streaming(
                [(1, "de", "Gute Beispiele helfen."), (2, "de", "Keine Ubersetzung.")],
                [(10, "en", "Good examples help."), (11, "en", "Examples are useful.")],
                [(1, 10), (1, 11), (10, 1)],
            )
        )

        self.assertEqual(
            rows,
            [
                ("de", "Gute Beispiele helfen.", "Good examples help."),
                ("de", "Keine Ubersetzung.", None),
            ],
        )

    def test_import_word_forms_preserves_same_form_with_different_bases(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "forms.tsv"
            db_path = temp / "context.db"
            source.write_text("saw\tsee\nsaw\tsaw\n", encoding="utf-8")
            config = normalize_config({"database_path": str(db_path), "language": "en"})

            result = import_word_forms_file(source, config)

            self.assertEqual(result.inserted, 2)
            conn = sqlite3.connect(str(db_path))
            try:
                rows = conn.execute(
                    "select form, base from word_forms where form = 'saw' order by base"
                ).fetchall()
                self.assertEqual(rows, [("saw", "saw"), ("saw", "see")])
            finally:
                conn.close()

    def test_replace_word_forms_rolls_back_if_a_large_import_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            source = temp / "forms.tsv"
            source.write_text("placeholder\n", encoding="utf-8")
            original = temp / "original.tsv"
            original.write_text("went\tgo\n", encoding="utf-8")
            db_path = temp / "context.db"
            config = normalize_config({"database_path": str(db_path), "language": "en"})
            import_word_forms_file(original, config)

            def broken_rows(_path):
                for index in range(1000):
                    yield "form%s" % index, "base"
                raise RuntimeError("broken word forms")

            with patch("contextual_review.importer.read_word_forms_file", side_effect=broken_rows):
                with self.assertRaisesRegex(RuntimeError, "broken word forms"):
                    import_word_forms_file(source, config, replace=True)

            conn = sqlite3.connect(str(db_path))
            try:
                self.assertEqual(
                    conn.execute("SELECT form, base FROM word_forms ORDER BY form, base").fetchall(),
                    [("went", "go")],
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
