"""Small, additive launch controls on Anki's deck screens."""

from __future__ import annotations

from .release import VERSION


def launcher_html() -> str:
    return '''<div id="contextual-review-launcher" style="margin:18px auto;text-align:center">
<button onclick="pycmd('contextual-review:start')">Start Contextual Review</button>
<button onclick="pycmd('contextual-review:version')">Version %s</button>
<button onclick="pycmd('contextual-review:bug')">Report a bug</button>
</div>''' % VERSION


def register_launcher(on_start, on_version, on_bug) -> None:
    from aqt import gui_hooks
    from aqt.deckbrowser import DeckBrowser
    from aqt.overview import Overview

    def overview_content(overview, content) -> None:
        if 'id="contextual-review-launcher"' not in content.table:
            content.table += launcher_html()

    def deck_content(deck_browser, content) -> None:
        if 'id="contextual-review-launcher"' not in content.tree:
            content.tree += launcher_html()

    callbacks = {
        "contextual-review:start": on_start,
        "contextual-review:version": on_version,
        "contextual-review:bug": on_bug,
    }

    def bridge(handled, message, context):
        if handled[0] or not isinstance(context, (DeckBrowser, Overview)):
            return handled
        callback = callbacks.get(message)
        if callback is None:
            return handled
        callback()
        return (True, None)

    gui_hooks.overview_will_render_content.append(overview_content)
    gui_hooks.deck_browser_will_render_content.append(deck_content)
    gui_hooks.webview_did_receive_js_message.append(bridge)
