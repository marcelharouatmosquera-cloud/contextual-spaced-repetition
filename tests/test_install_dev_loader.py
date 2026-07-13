from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER_PATH = ROOT / "scripts" / "install_dev_loader.py"


def load_installer():
    spec = importlib.util.spec_from_file_location("install_dev_loader", INSTALLER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class InstallDevLoaderTests(unittest.TestCase):
    def test_fresh_install_writes_loader_and_seeds_user_database(self) -> None:
        installer = load_installer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            target.parent.mkdir()

            summary = installer.install_dev_loader(target=target, source=ROOT)

            self.assertEqual(summary.written, 4)
            self.assertTrue(summary.seeded_database)
            self.assertFalse(summary.migrated_database)
            self.assertTrue((target / "__init__.py").exists())
            self.assertTrue((target / "manifest.json").exists())
            self.assertTrue((target / "config.json").exists())
            self.assertTrue((target / installer.DEV_MANIFEST).exists())
            self.assertTrue((target / "user_files" / "README.txt").exists())
            self.assertEqual(
                (target / "user_files" / "contextual_sentences.db").read_bytes(),
                (ROOT / "data" / "contextual_sentences.db").read_bytes(),
            )
            self.assertFalse((target / "contextual_review").exists())
            self.assertIn("SOURCE_ROOT", (target / "__init__.py").read_text(encoding="utf-8"))

            manifest = json.loads((target / installer.DEV_MANIFEST).read_text(encoding="utf-8"))
            self.assertEqual(manifest["source"], str(ROOT))

    def test_existing_user_state_is_preserved_and_old_runtime_is_removed(self) -> None:
        installer = load_installer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            stale_files = [
                target / "contextual_review" / "old.py",
                target / "scripts" / "sync_to_anki.py",
                target / "docs" / "old.md",
                target / "tests" / "test_old.py",
            ]
            for path in stale_files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("old", encoding="utf-8")
            (target / "data").mkdir(exist_ok=True)
            (target / "data" / "contextual_sentences.db").write_bytes(b"legacy db")
            (target / "meta.json").write_text("settings", encoding="utf-8")

            summary = installer.install_dev_loader(target=target, source=ROOT)

            self.assertGreaterEqual(summary.removed, 4)
            self.assertTrue(summary.migrated_database)
            self.assertFalse(summary.seeded_database)
            for path in stale_files:
                self.assertFalse(path.exists(), str(path))
            self.assertEqual((target / "meta.json").read_text(encoding="utf-8"), "settings")
            self.assertEqual((target / "user_files" / "contextual_sentences.db").read_bytes(), b"legacy db")
            self.assertEqual((target / "data" / "contextual_sentences.db").read_bytes(), b"legacy db")

    def test_existing_user_files_database_is_not_overwritten(self) -> None:
        installer = load_installer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            (target / "user_files").mkdir(parents=True)
            (target / "user_files" / "contextual_sentences.db").write_bytes(b"user db")
            (target / "data").mkdir()
            (target / "data" / "contextual_sentences.db").write_bytes(b"legacy db")

            summary = installer.install_dev_loader(target=target, source=ROOT)

            self.assertFalse(summary.migrated_database)
            self.assertFalse(summary.seeded_database)
            self.assertEqual((target / "user_files" / "contextual_sentences.db").read_bytes(), b"user db")

    def test_dry_run_does_not_mutate_target(self) -> None:
        installer = load_installer()
        with tempfile.TemporaryDirectory() as tempdir:
            target = Path(tempdir) / "addons21" / "contextual_review_addon"
            stale = target / "contextual_review" / "old.py"
            stale.parent.mkdir(parents=True)
            stale.write_text("old", encoding="utf-8")

            summary = installer.install_dev_loader(target=target, source=ROOT, dry_run=True)

            self.assertEqual(summary.written, 4)
            self.assertGreaterEqual(summary.removed, 1)
            self.assertTrue(summary.seeded_database)
            self.assertTrue(stale.exists())
            self.assertFalse((target / "__init__.py").exists())
            self.assertFalse((target / "user_files" / "contextual_sentences.db").exists())


if __name__ == "__main__":
    unittest.main()
