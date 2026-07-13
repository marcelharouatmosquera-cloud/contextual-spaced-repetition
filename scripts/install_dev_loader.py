#!/usr/bin/env python
"""Install a small Anki loader that runs this checkout directly."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.package_addon import validate_manifest
from scripts.sync_to_anki import (
    DEFAULT_TARGET,
    PRESERVED_FILES,
    PRESERVED_SUFFIXES,
    _clean_target,
)

DEV_MANIFEST = ".contextual_review_dev.json"
LOADER_FILES = {
    "__init__.py",
    "config.json",
    "manifest.json",
}


@dataclass(frozen=True)
class DevInstallSummary:
    target: Path
    source: Path
    written: int
    removed: int
    migrated_database: bool
    seeded_database: bool


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Installed Anki add-on directory where the development loader should live.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT,
        help="Checkout directory Anki should run directly.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing files.")
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Leave old copied runtime files in the installed add-on folder.",
    )
    args = parser.parse_args(argv)

    summary = install_dev_loader(
        target=args.target,
        source=args.source,
        dry_run=args.dry_run,
        clean=not args.no_clean,
    )

    action = "Would install" if args.dry_run else "Installed"
    print("%s development loader in %s" % (action, summary.target))
    print("Source checkout: %s" % summary.source)
    print("Loader/default files %s: %s" % ("to write" if args.dry_run else "written", summary.written))
    print("Stale copied item(s) %s: %s" % ("to remove" if args.dry_run else "removed", summary.removed))
    if summary.migrated_database:
        print("Preserved legacy database by copying data/contextual_sentences.db to user_files/contextual_sentences.db")
    if summary.seeded_database:
        print("Seeded user_files/contextual_sentences.db from the bundled smoke database")
    if not args.dry_run:
        print("Restart Anki to run the code from this checkout.")
    return 0


def install_dev_loader(
    target: Path = DEFAULT_TARGET,
    source: Path = ROOT,
    dry_run: bool = False,
    clean: bool = True,
) -> DevInstallSummary:
    target = target.expanduser().resolve()
    source = source.expanduser().resolve()
    if not target.parent.exists():
        raise RuntimeError("Anki addons21 directory does not exist: %s" % target.parent)
    if not (source / "contextual_review" / "__init__.py").exists():
        raise RuntimeError("Source checkout is missing contextual_review/__init__.py: %s" % source)
    validate_manifest(source / "manifest.json")

    removed = 0
    if clean:
        removed = _clean_target(target, LOADER_FILES, _protected_files(), dry_run)

    migrated_database = _migrate_legacy_database(target, dry_run)
    seeded_database = False
    if not migrated_database:
        seeded_database = _seed_database(target, source, dry_run)

    written = len(LOADER_FILES) + 1
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)
        _write_loader(target / "__init__.py", source)
        shutil.copy2(source / "manifest.json", target / "manifest.json")
        shutil.copy2(source / "config.json", target / "config.json")
        _write_dev_manifest(target, source)
        _ensure_user_files_readme(target, source)

    return DevInstallSummary(target, source, written, removed, migrated_database, seeded_database)


def _write_loader(path: Path, source: Path) -> None:
    path.write_text(_loader_source(source), encoding="utf-8")


def _loader_source(source: Path) -> str:
    source_literal = repr(str(source))
    return """\
\"\"\"Development loader for Contextual Spaced Repetition.

This file is intentionally tiny. The real add-on code is imported from the
working checkout recorded below.
\"\"\"

from __future__ import annotations

import os
import sys
from pathlib import Path

SOURCE_ROOT = Path(%s)
USER_ROOT = Path(__file__).resolve().parent

os.environ["CONTEXTUAL_REVIEW_USER_ROOT"] = str(USER_ROOT)
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

for module_name in list(sys.modules):
    if module_name == "contextual_review" or module_name.startswith("contextual_review."):
        del sys.modules[module_name]

from contextual_review import setup

setup(__name__)
""" % source_literal


def _write_dev_manifest(target: Path, source: Path) -> None:
    data = {
        "version": 1,
        "source": str(source),
        "loader_files": sorted(LOADER_FILES),
    }
    (target / DEV_MANIFEST).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _ensure_user_files_readme(target: Path, source: Path) -> None:
    destination = target / "user_files" / "README.txt"
    if destination.exists():
        return
    source_readme = source / "user_files" / "README.txt"
    if source_readme.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_readme, destination)


def _migrate_legacy_database(target: Path, dry_run: bool) -> bool:
    legacy = target / "data" / "contextual_sentences.db"
    destination = target / "user_files" / "contextual_sentences.db"
    if destination.exists() or not legacy.exists():
        return False
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy, destination)
    return True


def _seed_database(target: Path, source: Path, dry_run: bool) -> bool:
    destination = target / "user_files" / "contextual_sentences.db"
    source_database = source / "data" / "contextual_sentences.db"
    if destination.exists() or not source_database.exists():
        return False
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_database, destination)
    return True


def _protected_files() -> set[str]:
    protected = set(PRESERVED_FILES)
    protected.update("user_files/contextual_sentences%s" % suffix for suffix in PRESERVED_SUFFIXES)
    return protected


if __name__ == "__main__":
    raise SystemExit(main())
