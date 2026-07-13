from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SMOKE_PATH = ROOT / "scripts" / "smoke_review_loop.py"


def load_smoke_module():
    spec = importlib.util.spec_from_file_location("smoke_review_loop", SMOKE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeReviewLoopTests(unittest.TestCase):
    def test_smoke_review_loop_answers_expected_cards(self) -> None:
        module = load_smoke_module()

        result = module.run_smoke_review_loop()

        self.assertEqual(result["sentence"], "We review cards daily.")
        self.assertEqual(result["due_keys"], ["cards", "review"])
        self.assertEqual(result["answers"], [(101, 1), (102, 3)])
        self.assertEqual(result["answered_card_ids"], [101, 102])
        self.assertEqual(result["unknown_card_ids"], [101])
        self.assertEqual(result["known_card_ids"], [102])
        self.assertEqual(result["checkpoint_count"], 1)
        self.assertGreater(result["html_length"], 1000)


if __name__ == "__main__":
    unittest.main()
