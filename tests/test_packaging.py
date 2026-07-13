from __future__ import annotations

import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGER_PATH = ROOT / "scripts" / "package_addon.py"
BUILD_BATCH_PATH = ROOT / "build_addon.bat"


def load_packager():
    spec = importlib.util.spec_from_file_location("package_addon", PACKAGER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagingTests(unittest.TestCase):
    def test_windows_build_button_runs_verification_before_packaging(self) -> None:
        text = BUILD_BATCH_PATH.read_text(encoding="utf-8")

        self.assertIn("unittest discover -s tests", text)
        self.assertIn("scripts\\smoke_review_loop.py", text)
        self.assertIn("scripts\\package_addon.py", text)
        self.assertIn("explorer.exe /select", text)
        self.assertIn("--no-pause", text)

    def test_package_file_list_excludes_dev_artifacts(self) -> None:
        packager = load_packager()

        arcnames = {arcname for _, arcname in packager.package_files(ROOT)}

        self.assertIn("__init__.py", arcnames)
        self.assertIn("manifest.json", arcnames)
        self.assertIn("data/language_profiles.json", arcnames)
        self.assertIn("data/seed_word_forms.tsv", arcnames)
        self.assertIn("user_files/README.txt", arcnames)
        self.assertIn("docs/USER_GUIDE.md", arcnames)
        self.assertIn("contextual_review/diagnostics.py", arcnames)
        self.assertIn("contextual_review/debug_log.py", arcnames)
        self.assertIn("contextual_review/reviewer.py", arcnames)
        self.assertNotIn("user_files/contextual_review.log", arcnames)
        self.assertNotIn("tests/test_packaging.py", arcnames)
        self.assertFalse(any(name.startswith("IMPORTANT-Development instructions/") for name in arcnames))
        self.assertFalse(any("__pycache__" in name for name in arcnames))

    def test_package_addon_creates_valid_zip(self) -> None:
        packager = load_packager()
        with tempfile.TemporaryDirectory() as tempdir:
            temp = Path(tempdir)
            output = temp / "contextual_review_addon.ankiaddon"
            build_dir = temp / "build"

            packager.package_addon(output, build_dir)

            self.assertTrue(output.exists())
            self.assertTrue((build_dir / "manifest.json").exists())
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())

            self.assertIn("__init__.py", names)
            self.assertIn("config.json", names)
            self.assertIn("contextual_review/diagnostics.py", names)
            self.assertIn("contextual_review/debug_log.py", names)
            self.assertIn("data/contextual_sentences.db", names)
            self.assertIn("data/language_profiles.json", names)
            self.assertIn("data/seed_word_forms.tsv", names)
            self.assertIn("user_files/README.txt", names)
            self.assertNotIn("user_files/contextual_review.log", names)
            self.assertIn("docs/USER_GUIDE.md", names)
            self.assertNotIn("tests/test_packaging.py", names)


if __name__ == "__main__":
    unittest.main()
