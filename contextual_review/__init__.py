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

    def on_triggered() -> None:
        try:
            from .reviewer import open_contextual_review_dialog

            open_contextual_review_dialog(mw, addon_name)
        except Exception as exc:  # pragma: no cover - requires Anki runtime
            showInfo("Contextual Review could not start:\n\n%s" % exc)

    def on_settings() -> None:
        from .dialogs import open_settings_dialog

        open_settings_dialog(mw, addon_name)

    def on_favorites() -> None:
        from .dialogs import show_favorite_sentences_dialog

        show_favorite_sentences_dialog(mw, addon_name)

    def on_instructions() -> None:
        from .dialogs import show_instructions_dialog

        show_instructions_dialog(mw, addon_name)

    def on_diagnostics() -> None:
        from .dialogs import show_diagnostics_dialog

        show_diagnostics_dialog(mw, addon_name)

    menu = mw.form.menuTools.addMenu("Contextual Review")
    _ACTIONS.append(menu)

    for item in (
        ("Start Review", on_triggered),
        ("Favorite Sentences", on_favorites),
        None,
        ("Settings", on_settings),
        ("Quick Guide", on_instructions),
        ("Diagnostics", on_diagnostics),
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

    config_action = getattr(getattr(mw, "addonManager", None), "setConfigAction", None)
    if callable(config_action):
        try:
            config_action(addon_name, lambda: on_settings())
        except Exception:
            pass
