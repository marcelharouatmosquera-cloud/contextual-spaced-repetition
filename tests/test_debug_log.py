from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from contextual_review.config import USER_ROOT_ENV
from contextual_review.debug_log import append_debug_log, debug_log_path


class DebugLogTests(unittest.TestCase):
    def test_append_debug_log_writes_json_line_inside_user_files(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            old_root = os.environ.get(USER_ROOT_ENV)
            os.environ[USER_ROOT_ENV] = tempdir
            try:
                append_debug_log("answer", card_ids={2, 1}, nested={"ok": True})
                path = debug_log_path()
                payload = json.loads(path.read_text(encoding="utf-8").strip())
            finally:
                if old_root is None:
                    os.environ.pop(USER_ROOT_ENV, None)
                else:
                    os.environ[USER_ROOT_ENV] = old_root

        self.assertEqual(path, Path(tempdir) / "user_files" / "contextual_review.log")
        self.assertEqual(payload["event"], "answer")
        self.assertEqual(sorted(payload["card_ids"]), [1, 2])
        self.assertEqual(payload["nested"], {"ok": True})


if __name__ == "__main__":
    unittest.main()
