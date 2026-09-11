"""Public release identity and privacy-conscious reporting links."""

from __future__ import annotations

import platform
from urllib.parse import urlencode

VERSION = "1.0.0"
REPOSITORY_URL = "https://github.com/marcelharouatmosquera-cloud/contextual-spaced-repetition"


def version_details() -> str:
    try:
        from anki import version as anki_version
    except ImportError:
        anki_version = "unknown"
    return "Add-on: %s\nAnki: %s\nOS: %s %s" % (
        VERSION, anki_version, platform.system(), platform.release()
    )


def bug_report_url() -> str:
    # Only versions: never collection contents, paths, configuration or secrets.
    return REPOSITORY_URL + "/issues/new?" + urlencode({
        "template": "bug_report.yml",
        "environment": version_details(),
    })


def show_version_dialog(mw) -> None:
    from aqt.qt import QDialog, QDialogButtonBox, QLabel, QPushButton, QVBoxLayout
    from aqt.utils import openLink

    dialog = QDialog(mw)
    dialog.setWindowTitle("Contextual Review - Version")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Contextual Spaced Repetition\n\n" + version_details()))
    copy = QPushButton("Copy version info")
    copy.clicked.connect(lambda: mw.app.clipboard().setText(version_details()))
    layout.addWidget(copy)
    report = QPushButton("Report a bug")
    report.clicked.connect(lambda: openLink(bug_report_url()))
    layout.addWidget(report)
    releases = QPushButton("Downloads / release notes")
    releases.clicked.connect(lambda: openLink(REPOSITORY_URL + "/releases/latest"))
    layout.addWidget(releases)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()
