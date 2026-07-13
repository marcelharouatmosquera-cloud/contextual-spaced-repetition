#!/usr/bin/env python
"""Synchronize updated add-on files into Anki without overwriting user state."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence, Set

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.package_addon import package_files, validate_manifest, validate_package_files

DEFAULT_TARGET = Path(os.environ.get("APPDATA", "")) / "Anki2" / "addons21" / "contextual_review"
SYNC_MANIFEST = ".contextual_review_sync.json"
PRESERVED_FILES = {
    "meta.json",
    "data/contextual_sentences.db",
    "user_files/contextual_sentences.db",
}
PRESERVED_DIRS = {
    "user_files",
    "data/downloads",
}
PRESERVED_SUFFIXES = {
    ".db",
    ".sqlite",
    ".sqlite3",
}
MANAGED_DIRS = {
    "contextual_review",
    "data",
    "docs",
    "scripts",
}
MANAGED_ROOT_FILES = {
    "__init__.py",
    "config.json",
    "manifest.json",
    "README.md",
}
DEV_ARTIFACT_PARTS = {
    ".git",
    ".gitignore",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "tests",
    "IMPORTANT-Development instructions",
    "IMPORTANT FOR AI TO READ-Development instructions",
}


@dataclass(frozen=True)
class SyncSummary:
    copied: int
    preserved: int
    removed: int


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Installed Anki add-on directory to update.",
    )
    parser.add_argument(
        "--include-database",
        action="store_true",
        help=(
            "Also overwrite the bundled data/contextual_sentences.db smoke database. "
            "The user_files sentence database remains preserved."
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="Show what would be copied without changing files.")
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Leave stale packaged files and development artifacts in the installed add-on directory.",
    )
    args = parser.parse_args(argv)

    summary = sync_to_anki(
        args.target,
        include_database=args.include_database,
        dry_run=args.dry_run,
        clean=not args.no_clean,
    )
    action = "Would copy" if args.dry_run else "Copied"
    remove_action = "would remove" if args.dry_run else "removed"
    print(
        "%s %s file(s) to %s; preserved %s file(s); %s %s stale item(s)."
        % (
            action,
            summary.copied,
            args.target,
            summary.preserved,
            remove_action,
            summary.removed,
        )
    )
    if not args.dry_run:
        print("Restart Anki to load the updated add-on files.")
    return 0


def sync_to_anki(
    target: Path,
    include_database: bool = False,
    dry_run: bool = False,
    clean: bool = True,
) -> SyncSummary:
    target = target.expanduser().resolve()
    if not target.parent.exists():
        raise RuntimeError("Anki addons21 directory does not exist: %s" % target.parent)

    files = package_files(ROOT)
    validate_package_files(files)
    validate_manifest(ROOT / "manifest.json")

    preserved = _preserved_files(include_database)
    package_arcnames = {arcname for _, arcname in files}
    copied = 0
    skipped = 0
    for source, arcname in files:
        destination = target / arcname
        if arcname in preserved and destination.exists():
            skipped += 1
            continue
        copied += 1
        if dry_run:
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    removed = 0
    if clean:
        removed = _clean_target(target, package_arcnames, preserved, dry_run)

    managed_arcnames = package_arcnames - preserved
    if not dry_run:
        _write_sync_manifest(target, managed_arcnames)
    return SyncSummary(copied, skipped, removed)


def _preserved_files(include_database: bool) -> Set[str]:
    preserved = set(PRESERVED_FILES)
    if include_database:
        preserved.discard("data/contextual_sentences.db")
    return preserved


def _clean_target(
    target: Path,
    package_arcnames: Set[str],
    preserved_files: Set[str],
    dry_run: bool,
) -> int:
    if not target.exists():
        return 0

    stale_paths = _stale_paths(target, package_arcnames, preserved_files)
    removed = 0
    for path in _without_nested_paths(stale_paths):
        if dry_run:
            removed += 1
            continue
        if _remove_path(path):
            removed += 1

    if not dry_run:
        removed += _remove_empty_managed_dirs(target, preserved_files)
    return removed


def _stale_paths(target: Path, package_arcnames: Set[str], preserved_files: Set[str]) -> Set[Path]:
    stale_paths: Set[Path] = set()

    for arcname in _read_sync_manifest(target) - package_arcnames:
        path = _target_path(target, arcname)
        if path is not None and path.exists() and not _is_protected_arcname(arcname, preserved_files):
            stale_paths.add(path)

    for path in target.rglob("*"):
        arcname = _arcname_for_target(path, target)
        if arcname is None or _is_protected_arcname(arcname, preserved_files):
            continue

        artifact_root = _dev_artifact_root(path, target)
        if artifact_root is not None:
            stale_paths.add(artifact_root)
            continue

        if path.is_file() and _is_managed_arcname(arcname) and arcname not in package_arcnames:
            stale_paths.add(path)

    return stale_paths


def _read_sync_manifest(target: Path) -> Set[str]:
    manifest_path = target / SYNC_MANIFEST
    if not manifest_path.exists():
        return set()
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    files = data.get("files", [])
    if not isinstance(files, list):
        return set()
    return {_normalize_arcname(item) for item in files if isinstance(item, str)}


def _write_sync_manifest(target: Path, managed_arcnames: Iterable[str]) -> None:
    target.mkdir(parents=True, exist_ok=True)
    manifest_path = target / SYNC_MANIFEST
    data = {
        "version": 1,
        "files": sorted(_normalize_arcname(arcname) for arcname in managed_arcnames),
    }
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _remove_empty_managed_dirs(target: Path, preserved_files: Set[str]) -> int:
    removed = 0
    directories = [path for path in target.rglob("*") if path.is_dir()]
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        arcname = _arcname_for_target(path, target)
        if arcname is None or _is_protected_arcname(arcname, preserved_files):
            continue
        if not _is_managed_arcname(arcname):
            continue
        try:
            path.rmdir()
        except OSError:
            continue
        removed += 1
    return removed


def _without_nested_paths(paths: Set[Path]) -> Sequence[Path]:
    ordered = sorted(paths, key=lambda item: (len(item.parts), str(item)))
    roots = []
    for path in ordered:
        if any(_is_relative_to(path, root) for root in roots):
            continue
        roots.append(path)
    return sorted(roots, key=lambda item: len(item.parts), reverse=True)


def _remove_path(path: Path) -> bool:
    try:
        if path.is_dir():
            shutil.rmtree(path, onerror=_make_writable_and_retry)
            return True
        if path.exists():
            _unlink(path)
            return True
    except OSError as error:
        print("Warning: could not remove stale item %s: %s" % (path, error), file=sys.stderr)
    return False


def _make_writable_and_retry(function, path: str, exc_info) -> None:
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        function(path)
    except OSError:
        raise exc_info[1]


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except PermissionError:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        path.unlink()


def _dev_artifact_root(path: Path, target: Path) -> Optional[Path]:
    try:
        relative = path.relative_to(target)
    except ValueError:
        return None
    parts = relative.parts
    for index, part in enumerate(parts):
        if _is_dev_artifact_part(part):
            return target.joinpath(*parts[: index + 1])
    return None


def _is_dev_artifact_part(part: str) -> bool:
    return part in DEV_ARTIFACT_PARTS


def _is_managed_arcname(arcname: str) -> bool:
    if arcname in MANAGED_ROOT_FILES:
        return True
    root = arcname.split("/", 1)[0]
    return root in MANAGED_DIRS


def _is_protected_arcname(arcname: str, preserved_files: Set[str]) -> bool:
    arcname = _normalize_arcname(arcname)
    if arcname == SYNC_MANIFEST or arcname in preserved_files:
        return True
    if Path(arcname).suffix.lower() in PRESERVED_SUFFIXES:
        return True
    return any(arcname == directory or arcname.startswith(directory + "/") for directory in PRESERVED_DIRS)


def _target_path(target: Path, arcname: str) -> Optional[Path]:
    arcname = _normalize_arcname(arcname)
    if not arcname or arcname.startswith("../") or "/../" in arcname:
        return None
    path = (target / Path(*arcname.split("/"))).resolve()
    if path == target or _is_relative_to(path, target):
        return path
    return None


def _arcname_for_target(path: Path, target: Path) -> Optional[str]:
    try:
        return path.relative_to(target).as_posix()
    except ValueError:
        return None


def _normalize_arcname(value: str) -> str:
    return value.replace("\\", "/").strip("/")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
