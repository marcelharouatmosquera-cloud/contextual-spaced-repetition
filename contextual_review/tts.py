"""On-demand Microsoft Edge speech synthesis with a small disposable cache."""

from __future__ import annotations

import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Dict

from .config import addon_user_root
from .language_profiles import normalize_language_code


TTS_CACHE_PATH = Path("user_files") / "tts_cache"
TTS_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
TTS_CACHE_MAX_BYTES = 100 * 1024 * 1024

# One neutral neural voice for every language profile shipped with the add-on.
EDGE_VOICES: Dict[str, str] = {
    "ar": "ar-SA-ZariyahNeural",
    "da": "da-DK-ChristelNeural",
    "de": "de-DE-KatjaNeural",
    "el": "el-GR-AthinaNeural",
    "en": "en-US-EmmaMultilingualNeural",
    "es": "es-ES-ElviraNeural",
    "fi": "fi-FI-NooraNeural",
    "fr": "fr-FR-DeniseNeural",
    "it": "it-IT-ElsaNeural",
    "ja": "ja-JP-NanamiNeural",
    "ko": "ko-KR-SunHiNeural",
    "nl": "nl-NL-ColetteNeural",
    "pl": "pl-PL-ZofiaNeural",
    "pt": "pt-PT-RaquelNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "sv": "sv-SE-SofieNeural",
    "tr": "tr-TR-EmelNeural",
    "uk": "uk-UA-PolinaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
}
DEFAULT_EDGE_VOICE = EDGE_VOICES["en"]


def synthesize_sentence(text: str, language: str) -> Path:
    """Return a cached MP3, obtaining it from Edge's online service if needed."""
    sentence = str(text or "").strip()
    if not sentence:
        raise ValueError("There is no sentence to read.")

    voice = voice_for_language(language)
    cache_dir = tts_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cleanup_tts_cache(cache_dir)

    digest = hashlib.sha256(
        ("edge-tts-v1\0%s\0%s" % (voice, sentence)).encode("utf-8")
    ).hexdigest()
    output_path = cache_dir / (digest + ".mp3")
    if output_path.is_file() and output_path.stat().st_size > 0:
        os.utime(output_path, None)
        return output_path

    temporary_path = cache_dir / (digest + ".tmp")
    try:
        edge_tts = _load_edge_tts()
        edge_tts.Communicate(
            sentence,
            voice,
            connect_timeout=8,
            receive_timeout=20,
        ).save_sync(str(temporary_path))
        if not temporary_path.is_file() or temporary_path.stat().st_size <= 0:
            raise RuntimeError("The speech service returned no audio.")
        os.replace(str(temporary_path), str(output_path))
    except Exception:
        try:
            temporary_path.unlink()
        except OSError:
            pass
        raise
    return output_path


def voice_for_language(language: str) -> str:
    return EDGE_VOICES.get(normalize_language_code(language), DEFAULT_EDGE_VOICE)


def tts_cache_dir() -> Path:
    return (addon_user_root() / TTS_CACHE_PATH).resolve()


def cleanup_tts_cache(cache_dir: Path | None = None) -> None:
    """Remove week-old files, then keep the remaining cache below 100 MB."""
    directory = cache_dir or tts_cache_dir()
    if not directory.exists():
        return
    now = time.time()
    files = []
    for path in directory.glob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if path.suffix == ".tmp" or now - stat.st_mtime > TTS_CACHE_MAX_AGE_SECONDS:
            try:
                path.unlink()
            except OSError:
                pass
            continue
        files.append((stat.st_mtime, stat.st_size, path))

    total = sum(size for _modified, size, _path in files)
    for _modified, size, path in sorted(files):
        if total <= TTS_CACHE_MAX_BYTES:
            break
        try:
            path.unlink()
            total -= size
        except OSError:
            pass


def _load_edge_tts():
    try:
        import edge_tts

        return edge_tts
    except ImportError:
        vendor_path = Path(__file__).resolve().parent / "_vendor"
        if str(vendor_path) not in sys.path:
            # Append so Anki's own compatible libraries remain authoritative.
            sys.path.append(str(vendor_path))
        try:
            import edge_tts

            return edge_tts
        except ImportError as exc:
            raise RuntimeError("The bundled Edge TTS component could not be loaded.") from exc
