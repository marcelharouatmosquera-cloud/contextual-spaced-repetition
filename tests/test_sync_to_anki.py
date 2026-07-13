from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNC_PATH = ROOT / "scripts" / "sync_to_anki.py"


def load_syncer():
    spec = importlib.util.spec_from_file_location("sync_to_anki", SYNC_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class SyncToAnkiTests(unittest.TestCase):
    def test_default_target_matches_packaged_addon_folder(self) -> None:
        syncer = load_syncer()

        self.assertEqual(syncer.DEFAULT_TARGET.name, "contextual_review")

    def test_fresh_sync_copies_packaged_files_and_seed_database(self) -> None:
        syncer = load_syncer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            target.parent.mkdir()

            summary = syncer.sync_to_anki(target)

            self.assertGreater(summary.copied, 0)
            self.assertTrue((target / "__init__.py").exists())
            self.assertTrue((target / "contextual_review" / "reviewer.py").exists())
            self.assertTrue((target / "data" / "contextual_sentences.db").exists())
            self.assertTrue((target / "user_files" / "README.txt").exists())
            self.assertTrue((target / syncer.SYNC_MANIFEST).exists())
            self.assertEqual(
                (target / "data" / "contextual_sentences.db").read_bytes(),
                (ROOT / "data" / "contextual_sentences.db").read_bytes(),
            )

    def test_existing_user_state_is_preserved(self) -> None:
        syncer = load_syncer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            (target / "data").mkdir(parents=True)
            (target / "user_files").mkdir()
            (target / "data" / "contextual_sentences.db").write_bytes(b"user data db")
            (target / "user_files" / "contextual_sentences.db").write_bytes(b"user files db")
            (target / "meta.json").write_text("user settings", encoding="utf-8")

            summary = syncer.sync_to_anki(target)

            self.assertEqual(summary.preserved, 1)
            self.assertEqual((target / "data" / "contextual_sentences.db").read_bytes(), b"user data db")
            self.assertEqual(
                (target / "user_files" / "contextual_sentences.db").read_bytes(),
                b"user files db",
            )
            self.assertEqual((target / "meta.json").read_text(encoding="utf-8"), "user settings")

    def test_clean_removes_stale_managed_files_and_dev_artifacts(self) -> None:
        syncer = load_syncer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            target.parent.mkdir()
            stale_files = [
                target / "contextual_review" / "old_module.py",
                target / "scripts" / "sync_to_anki.py",
                target / "docs" / "old.md",
                target / "data" / "old.txt",
                target / "tests" / "test_old.py",
                target / ".git" / "config",
                target / "dist" / "build.txt",
                target / "__pycache__" / "old.pyc",
            ]
            preserved_files = [
                target / "data" / "downloads" / "eng_sentences.tsv.bz2",
                target / "data" / "custom.sqlite",
                target / "user_files" / "contextual_sentences.db",
                target / "notes.txt",
            ]
            for path in stale_files + preserved_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("x", encoding="utf-8")

            summary = syncer.sync_to_anki(target)

            self.assertGreaterEqual(summary.removed, 7)
            for path in stale_files:
                self.assertFalse(path.exists(), str(path))
            self.assertFalse((target / "tests").exists())
            self.assertFalse((target / ".git").exists())
            self.assertFalse((target / "dist").exists())
            self.assertFalse((target / "__pycache__").exists())
            for path in preserved_files:
                self.assertTrue(path.exists(), str(path))
            self.assertTrue((target / "scripts" / "build_corpus.py").exists())

    def test_clean_removes_read_only_dev_artifacts(self) -> None:
        syncer = load_syncer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            target.parent.mkdir()
            stale = target / ".git" / "objects" / "00" / "object"
            stale.parent.mkdir(parents=True)
            stale.write_text("x", encoding="utf-8")
            os.chmod(stale, stat.S_IREAD)

            try:
                summary = syncer.sync_to_anki(target)
            finally:
                if stale.exists():
                    os.chmod(stale, stat.S_IREAD | stat.S_IWRITE)

            self.assertGreaterEqual(summary.removed, 1)
            self.assertFalse((target / ".git").exists())

    def test_dry_run_does_not_mutate_target(self) -> None:
        syncer = load_syncer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            target.parent.mkdir()
            stale = target / "contextual_review" / "old_module.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("x", encoding="utf-8")

            summary = syncer.sync_to_anki(target, dry_run=True)

            self.assertGreater(summary.copied, 0)
            self.assertEqual(summary.removed, 1)
            self.assertTrue(stale.exists())
            self.assertFalse((target / "__init__.py").exists())
            self.assertFalse((target / syncer.SYNC_MANIFEST).exists())


if __name__ == "__main__":
    unittest.main()
