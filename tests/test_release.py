from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from contextual_review.launcher import register_launcher
from contextual_review.release import VERSION, bug_report_url


class ReleaseTests(unittest.TestCase):
    def test_report_prefills_only_versions(self):
        with patch.dict(sys.modules, {"anki": SimpleNamespace(version="25.09")}):
            query = parse_qs(urlparse(bug_report_url()).query)
        self.assertEqual(set(query), {"template", "environment"})
        self.assertEqual(query["template"], ["bug_report.yml"])
        self.assertIn("Add-on: " + VERSION, query["environment"][0])
        self.assertIn("Anki: 25.09", query["environment"][0])
        self.assertEqual(len(query["environment"][0].splitlines()), 3)

    def test_deck_controls_preserve_content_and_route_only_owned_messages(self):
        class DeckBrowser: pass
        class Overview: pass
        hooks = SimpleNamespace(overview_will_render_content=[],
                                deck_browser_will_render_content=[],
                                webview_did_receive_js_message=[])
        calls = []
        with patch.dict(sys.modules, {
            "aqt": SimpleNamespace(gui_hooks=hooks),
            "aqt.deckbrowser": SimpleNamespace(DeckBrowser=DeckBrowser),
            "aqt.overview": SimpleNamespace(Overview=Overview),
        }):
            register_launcher(lambda: calls.append("start"),
                              lambda: calls.append("version"), lambda: calls.append("bug"))
        for hook, context, field in (
            (hooks.overview_will_render_content[0], Overview(), "table"),
            (hooks.deck_browser_will_render_content[0], DeckBrowser(), "stats"),
        ):
            content = SimpleNamespace(**{field: "existing content"})
            hook(context, content)
            hook(context, content)
            html = getattr(content, field)
            self.assertTrue(html.startswith("existing content"))
            self.assertEqual(html.count('id="contextual-review-launcher"'), 1)
            self.assertIn("Version " + VERSION, html)
        bridge = hooks.webview_did_receive_js_message[0]
        for command in ("start", "version", "bug"):
            self.assertEqual(bridge((False, None), "contextual-review:" + command, Overview()), (True, None))
        self.assertEqual(calls, ["start", "version", "bug"])
        for handled, message, context in (
            ((True, "owned"), "contextual-review:start", Overview()),
            ((False, None), "other-addon:start", DeckBrowser()),
            ((False, None), "contextual-review:start", object()),
        ):
            self.assertEqual(bridge(handled, message, context), handled)
        self.assertEqual(len(calls), 3)
