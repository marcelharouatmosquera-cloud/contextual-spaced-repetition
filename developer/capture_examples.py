"""Render documentation examples using real widgets and a disposable collection.

Run with a Python environment containing Anki and PyQt6.
No installed add-ons, personal collections, network calls, or cursor captures.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aqt.qt import QApplication, QDialog, QEventLoop, QFont, QFontDatabase, QMessageBox, QPushButton, QTimer, QWidget
import anki.lang
from anki.collection import Collection
import aqt

from contextual_review import dialogs
from contextual_review.config import DEFAULT_CONFIG
from contextual_review.corpus import initialize_database
from contextual_review.types import ReviewTask, TargetWordDefinition, Token
from contextual_review.web import render_task_html

OUT = ROOT / "docs" / "images"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])
app.setStyle("Fusion")
for font in ("segoeui.ttf", "segoeuib.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
app.setFont(QFont("Segoe UI", 10))
anki.lang.set_lang("en")


def settle(milliseconds=200):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def save(widget, name):
    app.processEvents()
    assert widget.grab().save(str(OUT / name), "PNG")
    print(name, widget.width(), widget.height(), flush=True)


with tempfile.TemporaryDirectory(prefix="contextual-docs-") as directory:
    base = Path(directory)
    col = Collection(str(base / "collection.anki2"))
    deck = col.decks.id("German example deck")
    col.decks.select(deck)
    model = col.models.new("Example vocabulary")
    for field in ("German", "English", "Audio"):
        col.models.add_field(model, col.models.new_field(field))
    for name, question in (("Recognition", "German"), ("Recall", "English")):
        template = col.models.new_template(name)
        template["qfmt"] = "{{" + question + "}}"
        template["afmt"] = "{{German}}<hr>{{English}}"
        col.models.add_template(model, template)
    col.models.add(model)
    for word, meaning in (("trinken", "to drink"), ("Kaffee", "coffee"), ("morgen", "tomorrow")):
        note = col.new_note(model)
        note["German"], note["English"] = word, meaning
        col.add_note(note, deck)
    corpus = base / "sentences.db"
    initialize_database(corpus)
    config = dict(DEFAULT_CONFIG, language="de", native_language="en",
                  target_field="German", dictionary_field="English",
                  database_path=str(corpus), solution_fields=[{"field": "English"}])
    mw = QWidget()
    mw.col, mw.app = col, app
    mw.addonManager = SimpleNamespace(getConfig=lambda _: config.copy())
    aqt.mw = mw

    # Capture the real settings editor and the real confirmation it opens.
    original_exec = QDialog.exec

    def capture_exec(dialog):
        if "Contextual Review Settings" not in dialog.windowTitle():
            return original_exec(dialog)
        dialog.resize(920, 1060)
        dialog.show()
        settle()
        save(dialog, "setup.png")

        def capture_preview():
            modal = QApplication.activeModalWidget()
            if not isinstance(modal, QMessageBox):
                raise RuntimeError("Auto-Configure confirmation did not open")
            save(modal, "auto-configure.png")
            modal.done(QMessageBox.StandardButton.Yes)

        QTimer.singleShot(150, capture_preview)
        next(b for b in dialog.findChildren(QPushButton)
             if b.text() == "Preview Auto-Configure Fields").click()
        # Applying the preview updates the editor; cancel to avoid a config write.
        dialog.close()
        return QDialog.DialogCode.Rejected

    QDialog.exec = capture_exec
    dialogs._open_settings_editor_dialog(mw, "example", "German example deck")
    QDialog.exec = original_exec
    col.close()

    # Same HTML renderer as the installed review. Numbers and cards are examples.
    tokens = [Token("Wir ", "", False),
              Token("trinken", "trinken", True, True, "trinken", "trinken", (1,), "recall", "to drink"),
              Token(" morgens ", "", False),
              Token("Kaffee", "kaffee", True, True, "kaffee", "Kaffee", (2,), "recall", "coffee"),
              Token(".", "", False)]
    targets = tuple(TargetWordDefinition(i, word, meaning, good_interval="4d",
                    again_interval="<1m", direction="recall")
                    for i, word, meaning in ((1, "trinken", "to drink"), (2, "Kaffee", "coffee")))
    task = ReviewTask(1, "de", "Wir trinken morgens Kaffee.", "We drink coffee in the morning.",
                      tokens, {"trinken": [1], "kaffee": [2]}, targets)
    html = render_task_html(task, dark_mode=True, font_size=34,
                           progress_completed=8, progress_learning=3, progress_total=20)
    html = '<meta charset="utf-8"><script>window.pycmd = function() {};</script>' + html
    preview_dir = ROOT / "dist" / "docs-preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    (preview_dir / "review.html").write_text(html, encoding="utf-8")
    print("Review HTML ready for browser capture", flush=True)
