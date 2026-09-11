"""Contextual review add-on bootstrap."""

from __future__ import annotations

from typing import Any, List

_ACTIONS: List[Any] = []


def setup(addon_name: str) -> None:
    """Register the menu item when running inside Anki."""
    try:
        from aqt import mw
        from aqt.qt import QAction
        from aqt.utils import showInfo
    except Exception:
        return

    global _ACTIONS
    if _ACTIONS or mw is None:
        return

    def guarded(action: str):
        def decorate(callback: Any) -> Any:
            def run() -> None:
                try:
                    callback()
                except Exception as exc:  # pragma: no cover - requires Anki runtime
                    showInfo("Contextual Review could not %s:\n\n%s" % (action, exc))

            return run

        return decorate

    @guarded("start")
    def on_triggered() -> None:
        from .reviewer import open_contextual_review_dialog

        open_contextual_review_dialog(mw, addon_name)

    @guarded("open Settings")
    def on_settings() -> None:
        from .dialogs import open_settings_dialog

        open_settings_dialog(mw, addon_name)

    @guarded("open Favorite Sentences")
    def on_favorites() -> None:
        from .dialogs import show_favorite_sentences_dialog

        show_favorite_sentences_dialog(mw, addon_name)

    @guarded("open Last 100 Sentences")
    def on_recent_sentences() -> None:
        from .dialogs import show_recent_sentences_dialog

        show_recent_sentences_dialog(mw, addon_name)

    @guarded("open the Quick Guide")
    def on_instructions() -> None:
        from .dialogs import show_instructions_dialog

        show_instructions_dialog(mw, addon_name)

    @guarded("open Diagnostics")
    def on_diagnostics() -> None:
        from .dialogs import show_diagnostics_dialog

        show_diagnostics_dialog(mw, addon_name)

    @guarded("open version information")
    def on_version() -> None:
        from .release import show_version_dialog

        show_version_dialog(mw)

    @guarded("open the bug report form")
    def on_bug() -> None:
        from aqt.utils import openLink
        from .release import bug_report_url

        openLink(bug_report_url())

    menu = mw.form.menuTools.addMenu("Contextual Review")
    _ACTIONS.append(menu)

    for item in (
        ("Start Review", on_triggered),
        ("Favorite Sentences", on_favorites),
        ("Last 100 Sentences", on_recent_sentences),
        None,
        ("Settings", on_settings),
        ("Quick Guide", on_instructions),
        ("Diagnostics", on_diagnostics),
        ("Version / About", on_version),
        ("Report a bug", on_bug),
    ):
        if item is None:
            add_separator = getattr(menu, "addSeparator", None)
            if callable(add_separator):
                add_separator()
            continue
        label, callback = item
        action = QAction(label, mw)
        action.triggered.connect(callback)
        menu.addAction(action)
        _ACTIONS.append(action)

    from .launcher import register_launcher

    register_launcher(on_triggered, on_version, on_bug)

    config_action = getattr(getattr(mw, "addonManager", None), "setConfigAction", None)
    if callable(config_action):
        try:
            config_action(addon_name, lambda: on_settings())
        except Exception:
            pass
