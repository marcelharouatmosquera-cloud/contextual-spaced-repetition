#!/usr/bin/env python
"""Build a release-ready .ankiaddon package."""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_BUILD_DIR = ROOT / "dist" / "contextual_review_addon"
DEFAULT_OUTPUT = ROOT / "dist" / "contextual_review_addon.ankiaddon"
INCLUDE_PATHS = (
    "__init__.py",
    "manifest.json",
    "config.json",
    "README.md",
    "contextual_review",
    "data",
    "docs",
    "user_files",
    "scripts/build_corpus.py",
)
REQUIRED_FILES = {
    "__init__.py",
    "manifest.json",
    "config.json",
    "contextual_review/__init__.py",
    "contextual_review/reviewer.py",
    "contextual_review/anki_bridge.py",
    "contextual_review/corpus.py",
    "contextual_review/diagnostics.py",
    "contextual_review/web.py",
    "data/contextual_sentences.db",
    "data/language_profiles.json",
    "user_files/README.txt",
}
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "downloads",
    "tts_cache",
    "dist",
    "tests",
    "IMPORTANT-Development instructions",
}
EXCLUDED_SUFFIXES = {".ankiaddon", ".log", ".pyc", ".pyo"}
ZIP_DATE = (2024, 1, 1, 0, 0, 0)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-build-dir", action="store_true", help="Create only the .ankiaddon zip")
    args = parser.parse_args(argv)

    output = package_addon(args.output, None if args.no_build_dir else args.build_dir)
    print("Wrote %s" % output)
    return 0


def package_addon(output_path: Path = DEFAULT_OUTPUT, build_dir: Optional[Path] = DEFAULT_BUILD_DIR) -> Path:
    files = package_files(ROOT)
    validate_package_files(files)
    validate_manifest(ROOT / "manifest.json")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if build_dir is not None:
        sync_build_dir(files, build_dir)
    write_ankiaddon(files, output_path)
    return output_path


def package_files(root: Path = ROOT) -> List[Tuple[Path, str]]:
    files: List[Tuple[Path, str]] = []
    for include in INCLUDE_PATHS:
        source = root / include
        if source.is_file():
            if _include_file(source, root):
                files.append((source, _arcname(source, root)))
            continue
        if source.is_dir():
            for file_path in sorted(source.rglob("*")):
                if file_path.is_file() and _include_file(file_path, root):
                    files.append((file_path, _arcname(file_path, root)))
    return sorted(files, key=lambda item: item[1])


def validate_package_files(files: Iterable[Tuple[Path, str]]) -> None:
    arcnames = {arcname for _, arcname in files}
    missing = sorted(REQUIRED_FILES - arcnames)
    if missing:
        raise RuntimeError("Package is missing required files: %s" % ", ".join(missing))

    forbidden = [
        arcname
        for arcname in arcnames
        if arcname.startswith("tests/")
        or arcname.startswith("IMPORTANT-Development instructions/")
        or "__pycache__/" in arcname
        or arcname.endswith(".pyc")
        or "/downloads/" in arcname
        or arcname.startswith("data/downloads/")
        or "/tts_cache/" in arcname
    ]
    if forbidden:
        raise RuntimeError("Package contains forbidden files: %s" % ", ".join(sorted(forbidden)))


def validate_manifest(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("package", "name", "min_point_version"):
        if key not in data:
            raise RuntimeError("manifest.json is missing %s" % key)
    if int(data["min_point_version"]) < 231000:
        raise RuntimeError("manifest.json must target Anki Qt6 builds")


def sync_build_dir(files: Iterable[Tuple[Path, str]], build_dir: Path) -> None:
    build_dir = build_dir.resolve()
    if build_dir.exists():
        if _is_relative_to(build_dir, (ROOT / "dist").resolve()):
            shutil.rmtree(build_dir)
        elif not any(build_dir.iterdir()):
            build_dir.rmdir()
        else:
            raise RuntimeError("Refusing to replace non-empty build directory outside dist: %s" % build_dir)
    build_dir.mkdir(parents=True)
    for source, arcname in files:
        destination = build_dir / arcname
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def write_ankiaddon(files: Iterable[Tuple[Path, str]], output_path: Path) -> None:
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for source, arcname in files:
            info = zipfile.ZipInfo(arcname.replace("\\", "/"), ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, source.read_bytes())


def _include_file(path: Path, root: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    return True


def _arcname(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
