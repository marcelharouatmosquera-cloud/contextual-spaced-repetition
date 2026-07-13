from __future__ import annotations

import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from contextual_review import tts
from contextual_review.config import USER_ROOT_ENV


class TtsTests(unittest.TestCase):
    def test_language_selects_a_normal_matching_voice(self) -> None:
        self.assertEqual(tts.voice_for_language("de-DE"), "de-DE-KatjaNeural")
        self.assertEqual(tts.voice_for_language("jpn"), "ja-JP-NanamiNeural")

    def test_synthesis_is_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            calls = []

            class FakeCommunicate:
                def __init__(self, text, voice, **kwargs):
                    calls.append((text, voice))

                def save_sync(self, path):
                    Path(path).write_bytes(b"mp3")

            original_loader = tts._load_edge_tts
            tts._load_edge_tts = lambda: SimpleNamespace(Communicate=FakeCommunicate)
            try:
                first = tts.synthesize_sentence("Guten Tag.", "de")
                second = tts.synthesize_sentence("Guten Tag.", "de")
            finally:
                tts._load_edge_tts = original_loader
                if old_root is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = old_root

        self.assertEqual(first, second)
        self.assertEqual(len(calls), 1)

    def test_cleanup_deletes_week_old_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            cache = Path(tempdir)
            old_audio = cache / "old.mp3"
            recent_audio = cache / "recent.mp3"
            old_audio.write_bytes(b"old")
            recent_audio.write_bytes(b"recent")
            old_time = time.time() - tts.TTS_CACHE_MAX_AGE_SECONDS - 1
            os.utime(old_audio, (old_time, old_time))

            tts.cleanup_tts_cache(cache)

            self.assertFalse(old_audio.exists())
            self.assertTrue(recent_audio.exists())


if __name__ == "__main__":
    unittest.main()
