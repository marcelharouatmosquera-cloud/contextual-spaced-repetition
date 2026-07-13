from __future__ import annotations

import sys
import types
import unittest

import contextual_review as bootstrap


class FakeSignal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class FakeAction:
    def __init__(self, label: str, mw) -> None:
        self.label = label
        self.mw = mw
        self.triggered = FakeSignal()


class FakeMenu:
    def __init__(self, label: str = "") -> None:
        self.label = label
        self.actions = []
        self.submenus = []
        self.separators = 0

    def addAction(self, action) -> None:
        self.actions.append(action)

    def addMenu(self, label: str):
        submenu = FakeMenu(label)
        self.submenus.append(submenu)
        return submenu

    def addSeparator(self) -> None:
        self.separators += 1


class FakeForm:
    def __init__(self) -> None:
        self.menuTools = FakeMenu()


class FakeAddonManager:
    def __init__(self) -> None:
        self.config_action = None

    def setConfigAction(self, addon_name: str, callback) -> None:
        self.config_action = (addon_name, callback)


class FakeMw:
    def __init__(self) -> None:
        self.form = FakeForm()
        self.addonManager = FakeAddonManager()


class BootstrapTests(unittest.TestCase):
    def test_setup_registers_tools_menu_and_addon_config_action(self) -> None:
        mw = FakeMw()
        originals = {name: sys.modules.get(name) for name in ("aqt", "aqt.qt", "aqt.utils")}
        try:
            aqt = types.ModuleType("aqt")
            aqt.mw = mw
            qt = types.ModuleType("aqt.qt")
            qt.QAction = FakeAction
            utils = types.ModuleType("aqt.utils")
            utils.showInfo = lambda message: None
            sys.modules["aqt"] = aqt
            sys.modules["aqt.qt"] = qt
            sys.modules["aqt.utils"] = utils

            bootstrap._ACTIONS = []
            bootstrap.setup("contextual_review")

            self.assertEqual([menu.label for menu in mw.form.menuTools.submenus], ["Contextual Review"])
            submenu = mw.form.menuTools.submenus[0]
            labels = [action.label for action in submenu.actions]
            self.assertEqual(
                labels,
                [
                    "Start Review",
                    "Favorite Sentences",
                    "Settings",
                    "Quick Guide",
                    "Diagnostics",
                ],
            )
            self.assertEqual(submenu.separators, 1)
            self.assertEqual(mw.addonManager.config_action[0], "contextual_review")
            self.assertTrue(callable(mw.addonManager.config_action[1]))
        finally:
            bootstrap._ACTIONS = []
            for name, module in originals.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


if __name__ == "__main__":
    unittest.main()
