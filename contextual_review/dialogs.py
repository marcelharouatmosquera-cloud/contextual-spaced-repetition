"""PyQt dialogs and menu actions for settings and corpus import."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import (
    DEFAULT_CONFIG,
    deck_config_name,
    load_config,
    normalize_config,
    resolve_database_path,
    upsert_deck_config,
)
from .auto_config import auto_config_summary, detect_deck_configuration
from .diagnostics import collect_diagnostics, format_diagnostics
from .corpus import delete_sentences_for_language, sentence_count_for_language
from .importer import download_tatoeba_sentences, import_corpus_file, import_word_forms_file
from .language_profiles import load_language_profiles
from .favorites import favorite_sentences, remove_favorite_sentence

SENTENCE_FILE_FILTER = (
    "Sentence files (*.txt *.srt *.tsv *.csv *.bz2);;"
    "Plain text (*.txt);;"
    "Subtitles (*.srt);;"
    "Tables (*.tsv *.csv);;"
    "Compressed Tatoeba TSV (*.bz2);;"
    "All files (*.*)"
)

WORD_FORMS_FILE_FILTER = (
    "Word-form mapping files (*.tsv *.csv *.txt);;"
    "Tables (*.tsv *.csv);;"
    "All files (*.*)"
)

DATABASE_SUFFIXES = {".db", ".sqlite", ".sqlite3"}

INSTRUCTIONS_TEXT = (
    "Contextual Review: Quick Guide\n\n"
    "Safe to try\n"
    "- The add-on does not create, move, edit, or delete your decks or notes.\n"
    "- It reviews cards from the deck and study options you choose.\n"
    "- Opening the add-on, changing settings, or importing sentences does not schedule any cards.\n"
    "- Cards are scheduled only when you press Grade & Next: forgotten words receive Again and the rest receive Good.\n"
    "- Ctrl+Z immediately undoes the last contextual review batch.\n\n"
    "First-time setup\n"
    "1. Open Settings and choose the deck you want to configure.\n"
    "2. In Basic Setup, choose your language and map the target word, translation, and optional audio fields.\n"
    "3. Choose whether to review due cards, learn new cards, or include learning cards.\n"
    "4. Most people can leave Advanced / Nerd Settings unchanged.\n"
    "5. Add example sentences from the Sentence Library, or use Advanced settings to import your own file.\n"
    "6. Run Diagnostics. If every required check is OK, choose Start Review.\n\n"
    "One review, step by step\n"
    "1. Read the sentence. Highlighted words are linked to due cards in the active deck profile.\n"
    "2. Click only the words you did not remember. Leave remembered words unclicked.\n"
    "3. Choose Show Solution, or press Space/Enter, to reveal the translation, definitions, and interval previews.\n"
    "4. Choose Grade & Next, or press Space/Enter again, to submit the answers and continue.\n"
    "5. If you made a mistake, press Ctrl+Z before continuing.\n\n"
    "Sentence sources\n"
    "- The Sentence Library is the easiest starting point. It shows the current count and imports more when requested.\n"
    "- If Target language and Native language differ, linked Tatoeba translations are added when available.\n"
    "- Advanced settings can import .txt, .srt, .tsv, .csv, and .bz2 files. Good sources include subtitles and sentence lists you have permission to use.\n"
    "- A word list alone is not enough; the add-on needs complete sentences.\n"
    "- The sentence database is separate from your Anki collection. Maintenance controls remove sentences, never cards.\n\n"
    "Optional word forms\n"
    "- Use Import Word Forms when a sentence form should match a base word, such as went -> go or Hunde -> Hund.\n"
    "- Use two columns: sentence form first, base card word second.\n"
    "went\tgo\n"
    "eating\teat\n"
    "\u0434\u043e\u043c\u0430\t\u0434\u043e\u043c\n"
    "- Lemma family matching is enabled by default.\n\n"
    "Useful shortcuts\n"
    "- Space or Enter: show the solution, then submit.\n"
    "- 1 to 9: mark the corresponding target word as forgotten.\n"
    "- Ctrl+Z: undo the last submitted batch."
)

INSTRUCTIONS_HTML = """
<style>
  body { font-size: 14px; line-height: 1.45; margin: 18px; }
  h1 { font-size: 24px; margin: 0 0 6px; }
  h2 { font-size: 18px; margin: 22px 0 6px; }
  p { margin: 6px 0 10px; }
  ol, ul { margin-top: 6px; padding-left: 24px; }
  li { margin: 5px 0; }
  .safety {
    background: #eaf6ee;
    border: 1px solid #9ac7a7;
    border-radius: 8px;
    color: #173c23;
    padding: 10px 14px;
  }
  .note {
    background: #eef4fb;
    border-left: 4px solid #5f91c7;
    padding: 8px 12px;
  }
  code { background: rgba(127, 127, 127, 0.16); padding: 1px 4px; }
</style>
<h1>Contextual Review</h1>
<p>Review vocabulary from your existing Anki deck inside useful sentences.</p>

<div class="safety">
  <b>Safe to explore:</b> the add-on does not create or modify decks or notes.
  Opening it, changing settings, and importing sentences do not schedule cards.
  Cards change only when you press <b>Grade &amp; Next</b>.
</div>

<h2>First-time setup</h2>
<ol>
  <li><b>Choose the deck.</b> Open Settings and click the deck you want to configure.</li>
  <li><b>Complete Basic Setup.</b> Choose your language, map the target word,
      translation, and optional audio fields, then choose what to study today.</li>
  <li><b>Add sentences.</b> Use the Sentence Library in Basic Setup. Custom files
      and word forms remain available in Advanced settings.</li>
  <li><b>Run Diagnostics.</b> Resolve any required errors, then start reviewing.</li>
</ol>

<h2>How a review works</h2>
<ol>
  <li>Read the sentence. Highlighted words correspond to due Anki cards.</li>
  <li>Click only words you <b>did not remember</b>.</li>
  <li>Choose <b>Show Solution</b> to reveal translations, definitions, and interval previews.</li>
  <li>Choose <b>Grade &amp; Next</b>: clicked words receive <b>Again</b>; unclicked words receive <b>Good</b>.</li>
</ol>
<p class="note"><b>Made a mistake?</b> Press <b>Ctrl+Z</b> to undo the last submitted batch.</p>

<h2>Choosing sentence data</h2>
<ul>
  <li><b>Sentence Library</b> is the simplest starting point. It shows the current
      count and lets you import more.</li>
  <li><b>Import Custom Sentence File</b> in Advanced settings accepts subtitles
      or sentence lists you have permission to use. A word list alone is not enough.</li>
  <li>The sentence database is separate from your Anki collection.
      Maintenance controls remove imported sentences only.</li>
</ul>

<h2>Optional: match inflected forms</h2>
<p>Import a two-column word-form file when forms such as <code>went → go</code>
or <code>Hunde → Hund</code> should match. Then choose
<b>Vocabulary matching → Lemma family</b>.</p>

<h2>Shortcuts</h2>
<ul>
  <li><b>Space / Enter:</b> show the solution, then submit</li>
  <li><b>1–9:</b> mark a target word as forgotten</li>
  <li><b>Ctrl+Z:</b> undo the last submitted batch</li>
</ul>
"""

def open_settings_dialog(mw: Any, addon_name: str) -> None:  # pragma: no cover - Anki UI
    target_deck_name = _choose_settings_deck(mw)
    if target_deck_name:
        _open_settings_editor_dialog(mw, addon_name, target_deck_name)


def _choose_settings_deck(mw: Any) -> str:  # pragma: no cover - Anki UI
    from aqt.qt import (
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QVBoxLayout,
        QWidget,
    )

    deck_names = _deck_names(mw)
    current_deck = _selected_deck_name(mw)
    if current_deck and current_deck not in deck_names:
        deck_names.insert(0, current_deck)

    dialog = QDialog(mw)
    dialog.setWindowTitle("Choose Contextual Review Deck")
    dialog.resize(520, 560)
    layout = QVBoxLayout(dialog)

    heading = QLabel("<h2 style='margin-bottom: 2px;'>Choose a deck to configure</h2>")
    heading.setWordWrap(True)
    layout.addWidget(heading)

    selected = {"deck": ""}

    def choose(deck_name: str) -> None:
        selected["deck"] = str(deck_name or "").strip()
        dialog.accept()

    if current_deck:
        current_button = QPushButton("Configure selected deck\n%s" % current_deck)
        current_button.setMinimumHeight(64)
        current_button.clicked.connect(lambda: choose(current_deck))
        layout.addWidget(current_button)

    selector_row = QHBoxLayout()
    deck_selector = QComboBox()
    deck_selector.setEditable(True)
    for deck_name in deck_names:
        deck_selector.addItem(deck_name)
    if current_deck:
        deck_selector.setEditText(current_deck)
    open_selected = QPushButton("Open")
    open_selected.setMinimumHeight(36)
    open_selected.clicked.connect(lambda: choose(deck_selector.currentText()))
    selector_row.addWidget(deck_selector, 1)
    selector_row.addWidget(open_selected)
    layout.addLayout(selector_row)

    if deck_names:
        list_heading = QLabel("<b>Decks</b>")
        layout.addWidget(list_heading)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        deck_buttons = QVBoxLayout(content)
        for deck_name in deck_names:
            button = QPushButton(deck_name)
            button.setMinimumHeight(38)
            button.clicked.connect(lambda _checked=False, name=deck_name: choose(name))
            deck_buttons.addWidget(button)
        deck_buttons.addStretch(1)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return ""
    return selected["deck"]


def _open_settings_editor_dialog(
    mw: Any, addon_name: str, target_deck_name: str
) -> None:  # pragma: no cover - Anki UI
    from aqt.qt import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QTabWidget,
        QVBoxLayout,
        QWidget,
    )
    from aqt.utils import askUser, showInfo, showWarning

    target_deck_name = str(target_deck_name or "").strip()
    if not target_deck_name:
        showWarning("Choose a deck before editing Contextual Review settings.")
        return

    raw = _raw_config(mw, addon_name)
    config = load_config(mw, addon_name, deck_name=target_deck_name)
    available_fields = _available_note_fields(mw, "configured", target_deck_name)

    dialog = QDialog(mw)
    dialog.setWindowTitle("Contextual Review Settings - %s" % target_deck_name)
    dialog.resize(860, 760)
    dialog_layout = QVBoxLayout(dialog)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    content = QWidget()
    layout = QVBoxLayout(content)
    scroll.setWidget(content)
    dialog_layout.addWidget(scroll)

    deck_heading = QLabel(
        "<h2 style='margin-bottom: 2px;'>%s</h2>"
        "<div>These settings will be saved for this deck and its subdecks.</div>"
        % _escape_html(target_deck_name)
    )
    deck_heading.setWordWrap(True)
    layout.addWidget(deck_heading)

    tabs = QTabWidget()
    basic_tab = QWidget()
    advanced_tab = QWidget()
    basic_layout = QVBoxLayout(basic_tab)
    advanced_layout = QVBoxLayout(advanced_tab)
    tabs.addTab(basic_tab, "Basic Setup")
    tabs.addTab(advanced_tab, "Advanced / Nerd Settings")
    layout.addWidget(tabs)

    copy_row = QHBoxLayout()
    copy_source = QComboBox()
    copy_source.addItem("Copy settings from...", "")
    copy_source.addItem("Global defaults", "__global__")
    for label, deck_name in _deck_profile_choices(raw):
        if deck_name.casefold() != target_deck_name.casefold():
            copy_source.addItem(label, deck_name)
    copy_button = QPushButton("Copy")
    copy_button.setMinimumHeight(34)
    copy_row.addWidget(copy_source, 1)
    copy_row.addWidget(copy_button)
    advanced_layout.addLayout(copy_row)

    custom_search_query = QLineEdit(config.custom_search_query)
    custom_search_query.setPlaceholderText('is:due -card:2 -card:3 -card:Reverse')
    custom_search_query.setToolTip(
        "Standard Anki search for cards this add-on may review. Use it to exclude reverse cards, "
        'for example: is:due -card:2 -card:3 -card:Reverse'
    )
    target_field = _editable_combo(available_fields, config.target_field)
    target_field.setToolTip("Note field containing the word or expression being studied.")
    included_card_templates = QLineEdit(", ".join(config.included_card_templates))
    included_card_templates.setPlaceholderText("Optional: Card 1, Recognition, 1")
    included_card_templates.setToolTip(
        "Leave blank to allow all templates after the search filter. "
        "Use template names or card numbers to include only selected directions."
    )
    language = _language_combo(config.language)
    native_language = QLineEdit(config.native_language)
    native_language.setToolTip(
        "Language used for stored sentence translations when downloading paired Tatoeba data."
    )
    database_path = QLineEdit(config.database_path)
    dictionary_url = QLineEdit(config.dictionary_url_template)
    ignored_target_words = QLineEdit(", ".join(config.ignored_target_words))
    ignored_target_words.setPlaceholderText("Extra words to ignore, separated by commas")

    translation_spec, audio_spec, extra_solution_specs = _basic_solution_fields(config)
    translation_field = _editable_combo(
        available_fields,
        getattr(translation_spec, "field", "") or config.dictionary_field,
    )
    translation_field.setToolTip("Field containing the meaning or translation shown after answering.")
    audio_field = _optional_combo(
        available_fields,
        getattr(audio_spec, "field", ""),
        "No audio field",
    )
    audio_field.setToolTip("Optional field containing Anki [sound:...] audio.")

    matching_mode = QComboBox()
    matching_mode.addItem("Lemma family (recommended)", "lemma_family")
    matching_mode.addItem("Exact word form", "exact_form")
    _set_combo_value(matching_mode, config.matching_mode)

    target_extraction = QComboBox()
    target_extraction.addItem("Yes, focus on meaningful words", "content_words")
    target_extraction.addItem("No, use every word", "all_words")
    target_extraction.addItem("Use only the first word", "first_word")
    _set_combo_value(target_extraction, config.target_extraction_mode)

    min_words = _spin(config.min_sentence_words, 1, 50)
    max_words = _spin(config.max_sentence_words, 1, 80)
    max_due = _spin(config.max_due_cards, 1, 200)
    max_imported = _spin(config.max_imported_sentences, 0, 2000000)
    max_imported.setSingleStep(10000)
    max_imported.setSpecialValueText("Unlimited")
    future_due_days = _spin(config.future_due_days, 0, 60)
    future_due_days.setSuffix(" days")
    font_size = _spin(config.font_size, 18, 72)
    font_size.setSuffix(" px")
    include_new = QCheckBox()
    include_new.setChecked(config.include_new_cards)
    max_new = _spin(config.max_new_cards, 1, 100)
    max_new.setEnabled(config.include_new_cards)
    include_new.toggled.connect(max_new.setEnabled)
    include_due = QCheckBox("Review Due Cards")
    include_due.setChecked(config.include_due_cards)
    include_learning = QCheckBox()
    include_learning.setChecked(config.include_learning_cards)
    strict_import = QCheckBox()
    strict_import.setChecked(config.strict_import_filter)
    keep_downloads = QCheckBox()
    keep_downloads.setChecked(config.keep_downloaded_archives)
    keep_downloads.setToolTip(
        "Keep compressed Tatoeba downloads under data/downloads. Leave unchecked to stream imports without cache files."
    )
    require_target_on_question = QCheckBox()
    require_target_on_question.setChecked(config.require_target_on_question)
    require_target_on_question.setToolTip(
        "Skip cards whose front/question template does not contain the target field."
    )

    auto_group = QGroupBox("One-Click Setup")
    auto_layout = QVBoxLayout(auto_group)
    auto_explanation = QLabel(
        "Detect fields and keep only cards that show the language you are learning on the front."
    )
    auto_explanation.setWordWrap(True)
    auto_layout.addWidget(auto_explanation)
    auto_button = QPushButton("Preview Auto-Configure")
    auto_button.setMinimumHeight(38)
    auto_layout.addWidget(auto_button)
    auto_status = QLabel()
    auto_status.setWordWrap(True)
    auto_layout.addWidget(auto_status)
    basic_layout.addWidget(auto_group)

    language_group = QGroupBox("Step 1: Choose Language")
    language_form = QFormLayout(language_group)
    language_form.addRow("Language you are learning", language)
    basic_layout.addWidget(language_group)

    fields_group = QGroupBox("Step 2: Map Your Fields")
    fields_form = QFormLayout(fields_group)
    fields_form.addRow("Which field is the target word?", target_field)
    fields_form.addRow("Which field is the translation?", translation_field)
    fields_form.addRow("Which field has audio? (Optional)", audio_field)
    basic_layout.addWidget(fields_group)

    study_group = QGroupBox("Step 3: What to Study Today")
    study_layout = QVBoxLayout(study_group)
    study_layout.addWidget(include_due)
    new_row = QHBoxLayout()
    include_new.setText("Learn New Cards")
    new_row.addWidget(include_new)
    new_row.addWidget(QLabel("Max:"))
    new_row.addWidget(max_new)
    new_row.addStretch(1)
    study_layout.addLayout(new_row)
    include_learning.setText("Include Learning/Red Cards")
    study_layout.addWidget(include_learning)
    basic_layout.addWidget(study_group)

    library_group = QGroupBox("Sentence Library")
    library_layout = QVBoxLayout(library_group)
    library_count = QLabel()
    library_count.setWordWrap(True)
    library_layout.addWidget(library_count)
    recommendation = QLabel("Recommended: 100,000 to 200,000 sentences.")
    recommendation.setWordWrap(True)
    library_layout.addWidget(recommendation)

    library_target_row = QHBoxLayout()
    library_target_row.addWidget(QLabel("Library size:"))
    library_target = _spin(max(10000, config.max_imported_sentences), 10000, 2000000)
    library_target.setSingleStep(10000)
    library_target_row.addWidget(library_target)
    import_more = QPushButton("Import More")
    library_target_row.addWidget(import_more)
    library_target_row.addStretch(1)
    library_layout.addLayout(library_target_row)

    library_delete_row = QHBoxLayout()
    library_delete_row.addWidget(QLabel("Delete:"))
    delete_amount = _spin(10000, 1, 2000000)
    delete_amount.setSingleStep(10000)
    library_delete_row.addWidget(delete_amount)
    delete_some = QPushButton("Delete This Many")
    delete_all = QPushButton("Delete All for This Language")
    library_delete_row.addWidget(delete_some)
    library_delete_row.addWidget(delete_all)
    library_delete_row.addStretch(1)
    library_layout.addLayout(library_delete_row)

    library_note = QLabel(
        "The compressed download is only a few MB. The searchable library can use more space after import."
    )
    library_note.setWordWrap(True)
    library_layout.addWidget(library_note)
    basic_layout.addWidget(library_group)
    basic_layout.addStretch(1)

    cards_group = QGroupBox("Card Selection")
    cards_form = QFormLayout(cards_group)
    cards_form.addRow("Anki search query", custom_search_query)
    cards_form.addRow("Included card templates", included_card_templates)
    cards_form.addRow("Only test words that are on the Front of the card", require_target_on_question)
    cards_form.addRow("Include cards due within", future_due_days)
    cards_form.addRow("Maximum cards per search", max_due)

    behavior_group = QGroupBox("Language and Matching")
    behavior_form = QFormLayout(behavior_group)
    behavior_form.addRow("Translation language", native_language)
    behavior_form.addRow("Vocabulary matching", matching_mode)

    matching_group = QGroupBox("Sentence Matching")
    matching_form = QFormLayout(matching_group)
    matching_form.addRow("Ignore common words (like 'the', 'and', 'is')", target_extraction)
    matching_form.addRow("Extra ignored words", ignored_target_words)
    matching_form.addRow("Shortest sentence", min_words)
    matching_form.addRow("Longest sentence", max_words)

    advanced_group = QGroupBox("Storage and Advanced Options")
    advanced_form = QFormLayout(advanced_group)
    advanced_form.addRow("Sentence database", database_path)
    advanced_form.addRow("Dictionary URL", dictionary_url)
    advanced_form.addRow("Only use verified sentences", strict_import)
    advanced_form.addRow("Keep downloaded archives", keep_downloads)
    advanced_form.addRow("Sentence text size", font_size)

    maintenance_group = QGroupBox("Import and Maintenance")
    maintenance_layout = QVBoxLayout(maintenance_group)
    import_custom_button = QPushButton("Import Custom Sentence File")
    import_forms_button = QPushButton("Import Word Forms")
    delete_database_button = QPushButton("Delete Entire Sentence Database")
    maintenance_layout.addWidget(import_custom_button)
    maintenance_layout.addWidget(import_forms_button)
    maintenance_layout.addWidget(delete_database_button)

    solution_heading = QLabel(
        "<h3 style='margin-bottom: 2px;'>Additional fields after Show Solution</h3>"
        "<div>Optional advanced fields beyond the translation and audio selected in Basic Setup.</div>"
    )
    solution_heading.setWordWrap(True)
    advanced_layout.addWidget(solution_heading)

    solution_count = QLabel()
    solution_columns = QLabel(
        "<b>Field</b> &nbsp;&nbsp;&nbsp; <b>Display</b> &nbsp;&nbsp;&nbsp; "
        "<b>Custom label</b> &nbsp;&nbsp;&nbsp; <b>Audio option</b>"
    )
    advanced_layout.addWidget(solution_columns)
    solution_rows_layout = QVBoxLayout()
    solution_rows: list[Dict[str, Any]] = []

    def refresh_solution_count() -> None:
        count = len(solution_rows)
        solution_count.setText(
            "%s additional field%s configured" % (count, "" if count == 1 else "s")
        )

    def rebuild_solution_row_order() -> None:
        for index, row in enumerate(solution_rows):
            solution_rows_layout.removeWidget(row["widget"])
            solution_rows_layout.insertWidget(index, row["widget"])

    def move_solution_row(row: Dict[str, Any], offset: int) -> None:
        index = solution_rows.index(row)
        new_index = index + offset
        if new_index < 0 or new_index >= len(solution_rows):
            return
        solution_rows.pop(index)
        solution_rows.insert(new_index, row)
        rebuild_solution_row_order()

    def remove_solution_row(row: Dict[str, Any]) -> None:
        if row not in solution_rows:
            return
        solution_rows.remove(row)
        solution_rows_layout.removeWidget(row["widget"])
        row["widget"].deleteLater()
        refresh_solution_count()

    def clear_solution_rows() -> None:
        for row in list(solution_rows):
            remove_solution_row(row)

    def add_solution_row(spec: Any = None) -> None:
        widget = QWidget()
        row_layout = QHBoxLayout(widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        field_name = getattr(spec, "field", "") if spec is not None else ""
        label_text = getattr(spec, "label", "") if spec is not None else ""
        display_value = getattr(spec, "display", "auto") if spec is not None else "auto"
        autoplay_value = bool(getattr(spec, "autoplay", False)) if spec is not None else False

        field_combo = _editable_combo(available_fields, field_name)
        field_combo.setMinimumWidth(145)
        display_combo = QComboBox()
        for label, value in (
            ("Auto", "auto"),
            ("Text", "text"),
            ("Image", "image"),
            ("Audio", "audio"),
        ):
            display_combo.addItem(label, value)
        _set_combo_value(display_combo, display_value)
        label_input = QLineEdit(label_text)
        label_input.setPlaceholderText("Optional label")
        autoplay = QCheckBox("Auto-play")
        autoplay.setChecked(autoplay_value)
        up = QPushButton("Up")
        down = QPushButton("Down")
        remove = QPushButton("Remove")
        for button in (up, down):
            button.setMaximumWidth(54)

        row: Dict[str, Any] = {
            "widget": widget,
            "field": field_combo,
            "display": display_combo,
            "label": label_input,
            "autoplay": autoplay,
        }
        up.clicked.connect(lambda: move_solution_row(row, -1))
        down.clicked.connect(lambda: move_solution_row(row, 1))
        remove.clicked.connect(lambda: remove_solution_row(row))
        display_combo.currentIndexChanged.connect(
            lambda _index: autoplay.setEnabled(display_combo.currentData() in {"auto", "audio"})
        )
        autoplay.setEnabled(display_combo.currentData() in {"auto", "audio"})

        row_layout.addWidget(field_combo, 2)
        row_layout.addWidget(display_combo, 1)
        row_layout.addWidget(label_input, 2)
        row_layout.addWidget(autoplay)
        row_layout.addWidget(up)
        row_layout.addWidget(down)
        row_layout.addWidget(remove)
        solution_rows.append(row)
        solution_rows_layout.addWidget(widget)
        refresh_solution_count()

    base_solution_state = {
        "translation_field": getattr(translation_spec, "field", "") or config.dictionary_field,
        "translation_label": getattr(translation_spec, "label", ""),
        "audio_field": getattr(audio_spec, "field", ""),
        "audio_autoplay": bool(getattr(audio_spec, "autoplay", False)),
    }
    for spec in extra_solution_specs:
        add_solution_row(spec)

    def apply_solution_mapping(source_config: Any) -> None:
        source_translation, source_audio, source_extras = _basic_solution_fields(source_config)
        translation_name = (
            getattr(source_translation, "field", "") or source_config.dictionary_field
        )
        translation_field.setEditText(translation_name)
        _set_optional_combo_value(audio_field, getattr(source_audio, "field", ""))
        base_solution_state.update(
            {
                "translation_field": translation_name,
                "translation_label": getattr(source_translation, "label", ""),
                "audio_field": getattr(source_audio, "field", ""),
                "audio_autoplay": bool(getattr(source_audio, "autoplay", False)),
            }
        )
        clear_solution_rows()
        for spec in source_extras:
            add_solution_row(spec)

    def apply_editor_config(source_config: Any) -> None:
        custom_search_query.setText(source_config.custom_search_query)
        target_field.setEditText(source_config.target_field)
        included_card_templates.setText(", ".join(source_config.included_card_templates))
        require_target_on_question.setChecked(source_config.require_target_on_question)
        _set_combo_value(language, source_config.language)
        native_language.setText(source_config.native_language)
        _set_combo_value(matching_mode, source_config.matching_mode)
        _set_combo_value(target_extraction, source_config.target_extraction_mode)
        ignored_target_words.setText(", ".join(source_config.ignored_target_words))
        database_path.setText(source_config.database_path)
        dictionary_url.setText(source_config.dictionary_url_template)
        min_words.setValue(source_config.min_sentence_words)
        max_words.setValue(source_config.max_sentence_words)
        max_due.setValue(source_config.max_due_cards)
        max_imported.setValue(source_config.max_imported_sentences)
        library_target.setValue(max(10000, source_config.max_imported_sentences))
        future_due_days.setValue(source_config.future_due_days)
        font_size.setValue(source_config.font_size)
        include_due.setChecked(source_config.include_due_cards)
        include_new.setChecked(source_config.include_new_cards)
        max_new.setValue(source_config.max_new_cards)
        include_learning.setChecked(source_config.include_learning_cards)
        strict_import.setChecked(source_config.strict_import_filter)
        keep_downloads.setChecked(source_config.keep_downloaded_archives)
        apply_solution_mapping(source_config)

    def copy_selected_settings() -> None:
        source = str(copy_source.currentData() or "")
        if not source:
            return
        if source == "__global__":
            source_config = normalize_config(_global_config(raw))
        else:
            source_config = load_config(mw, addon_name, deck_name=source)
        apply_editor_config(source_config)

    advanced_layout.addWidget(solution_count)
    advanced_layout.addLayout(solution_rows_layout)

    solution_actions = QHBoxLayout()
    add_solution = QPushButton("Add solution field")
    refresh_field_choices = QPushButton("Refresh fields from selected deck")
    solution_actions.addWidget(add_solution)
    solution_actions.addWidget(refresh_field_choices)
    solution_actions.addStretch(1)
    advanced_layout.addLayout(solution_actions)
    advanced_layout.addWidget(behavior_group)
    advanced_layout.addWidget(cards_group)
    advanced_layout.addWidget(matching_group)
    advanced_layout.addWidget(advanced_group)
    advanced_layout.addWidget(maintenance_group)
    advanced_layout.addStretch(1)

    def refresh_discovered_fields() -> None:
        nonlocal available_fields
        available_fields = _available_note_fields(mw, "configured", target_deck_name)
        _replace_combo_items(target_field, available_fields)
        _replace_combo_items(translation_field, available_fields)
        _replace_optional_combo_items(audio_field, available_fields)
        for row in solution_rows:
            _replace_combo_items(row["field"], available_fields)

    def selected_language_code() -> str:
        return str(language.currentData() or language.currentText() or "en").strip()

    def auto_configure_deck() -> None:
        try:
            result = detect_deck_configuration(
                mw,
                target_deck_name,
                selected_language_code(),
                target_field.currentText(),
                translation_field.currentText(),
            )
        except Exception as exc:
            showWarning("Auto-Configure could not inspect this deck:\n\n%s" % exc)
            return
        profile = load_language_profiles().get(selected_language_code())
        language_name = profile.name if profile and profile.name else selected_language_code().upper()
        native_code = native_language.text().strip() or "en"
        native_profile = load_language_profiles().get(native_code)
        native_name = native_profile.name if native_profile and native_profile.name else native_code.upper()
        message = auto_config_summary(result, language_name, native_name)
        auto_status.setText(message)
        if not result.confident:
            showWarning(message)
            return

        preview = (
            "%s\n\n"
            "Target word field: %s\n"
            "Translation field: %s\n"
            "Audio field: %s\n"
            "Included card templates: %s\n\n"
            "Contextual Review is designed for %s to %s recognition cards. "
            "%s to %s production cards are excluded because the add-on needs "
            "a visible target-language word to find a matching sentence.\n\n"
            "Apply these settings?"
            % (
                message,
                result.target_field,
                result.translation_field,
                result.audio_field or "None",
                ", ".join(result.included_templates),
                language_name,
                native_name,
                native_name,
                language_name,
            )
        )
        if not askUser(preview, parent=dialog):
            auto_status.setText("Preview complete. No settings were changed.")
            return

        target_field.setEditText(result.target_field)
        translation_field.setEditText(result.translation_field)
        _set_optional_combo_value(audio_field, result.audio_field)
        included_card_templates.setText(", ".join(result.included_templates))
        require_target_on_question.setChecked(result.target_field_directly_on_question)
        custom_search_query.setText("is:due")
        _set_combo_value(matching_mode, "lemma_family")
        _set_combo_value(target_extraction, "content_words")
        min_words.setValue(4)
        max_words.setValue(15)
        base_solution_state.update(
            {
                "translation_field": result.translation_field,
                "translation_label": "",
                "audio_field": result.audio_field,
                "audio_autoplay": False,
            }
        )

    def current_library_config(import_limit: int = 0):
        return replace(
            config,
            language=selected_language_code(),
            native_language=native_language.text().strip() or "en",
            database_path=database_path.text().strip() or DEFAULT_CONFIG["database_path"],
            min_sentence_words=min_words.value(),
            max_sentence_words=max_words.value(),
            max_imported_sentences=max(0, int(import_limit)),
            strict_import_filter=strict_import.isChecked(),
            keep_downloaded_archives=keep_downloads.isChecked(),
        )

    def refresh_library_count() -> None:
        try:
            library_config = current_library_config(library_target.value())
            count = sentence_count_for_language(
                resolve_database_path(library_config),
                library_config.language,
            )
            profile = load_language_profiles().get(library_config.language)
            language_name = profile.name if profile and profile.name else library_config.language.upper()
            library_count.setText(
                "You currently have %s %s sentences." % (format(count, ","), language_name)
            )
            delete_amount.setMaximum(max(1, count))
            delete_some.setEnabled(count > 0)
            delete_all.setEnabled(count > 0)
        except Exception as exc:
            library_count.setText("Sentence count unavailable: %s" % exc)
            delete_some.setEnabled(False)
            delete_all.setEnabled(False)

    def import_more_sentences() -> None:
        library_config = current_library_config(library_target.value())
        try:
            current_count = sentence_count_for_language(
                resolve_database_path(library_config),
                library_config.language,
            )
        except Exception as exc:
            showWarning("Could not read the sentence library:\n\n%s" % exc)
            return
        remaining = max(0, library_target.value() - current_count)
        if remaining <= 0:
            showInfo("This language already has at least the selected number of sentences.")
            return
        import_config = replace(library_config, max_imported_sentences=remaining)
        _run_background(
            mw,
            "Importing more sentences...",
            lambda progress: download_tatoeba_sentences(
                import_config.language,
                import_config,
                replace=False,
                progress=progress,
            ),
            _tatoeba_import_done_message,
            after_done=refresh_library_count,
        )

    def delete_library_sentences(delete_everything: bool) -> None:
        library_config = current_library_config(library_target.value())
        amount = 0 if delete_everything else delete_amount.value()
        description = "all" if delete_everything else format(amount, ",")
        if not askUser(
            "Delete %s stored sentences for %s?" % (description, selected_language_code()),
            parent=dialog,
        ):
            return
        _run_background(
            mw,
            "Deleting stored sentences...",
            lambda _progress: delete_sentences_for_language(
                resolve_database_path(library_config),
                library_config.language,
                amount,
            ),
            lambda removed: "Deleted %s sentences." % format(removed, ","),
            after_done=refresh_library_count,
        )

    def import_custom_sentence_file() -> None:
        from aqt.qt import QFileDialog

        path, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            "Choose Sentence Corpus File",
            "",
            SENTENCE_FILE_FILTER,
        )
        if not path:
            return
        import_config = current_library_config(library_target.value())
        _run_background(
            mw,
            "Importing contextual corpus...",
            lambda progress: import_corpus_file(
                Path(path),
                import_config,
                replace=False,
                progress=progress,
            ),
            _corpus_import_done_message,
            after_done=refresh_library_count,
        )

    def import_word_form_file() -> None:
        from aqt.qt import QFileDialog

        path, _selected_filter = QFileDialog.getOpenFileName(
            dialog,
            "Choose Word-Forms File",
            "",
            WORD_FORMS_FILE_FILTER,
        )
        if not path:
            return
        import_config = current_library_config(library_target.value())
        _run_background(
            mw,
            "Importing word forms...",
            lambda progress: import_word_forms_file(
                Path(path),
                import_config,
                replace=False,
                progress=progress,
            ),
            _word_forms_import_done_message,
        )

    def delete_entire_sentence_database() -> None:
        database_config = current_library_config(library_target.value())
        try:
            database_path = resolve_database_path(database_config)
        except Exception as exc:
            showWarning("Could not resolve the sentence database:\n\n%s" % exc)
            return
        if not askUser(
            "Delete the entire sentence database at %s?" % database_path,
            parent=dialog,
        ):
            return
        try:
            removed_path, removed = delete_sentence_registry_file(database_config)
        except Exception as exc:
            showWarning("Could not delete the sentence database:\n\n%s" % exc)
            return
        showInfo(
            "Deleted the sentence database at %s."
            % removed_path
            if removed
            else "No sentence database was found at %s." % removed_path
        )
        refresh_library_count()

    add_solution.clicked.connect(lambda: add_solution_row())
    refresh_field_choices.clicked.connect(refresh_discovered_fields)
    copy_button.clicked.connect(copy_selected_settings)
    auto_button.clicked.connect(auto_configure_deck)
    language.currentIndexChanged.connect(lambda _index: refresh_library_count())
    database_path.editingFinished.connect(refresh_library_count)
    import_more.clicked.connect(import_more_sentences)
    delete_some.clicked.connect(lambda: delete_library_sentences(False))
    delete_all.clicked.connect(lambda: delete_library_sentences(True))
    import_custom_button.clicked.connect(import_custom_sentence_file)
    import_forms_button.clicked.connect(import_word_form_file)
    delete_database_button.clicked.connect(delete_entire_sentence_database)
    refresh_library_count()

    help_button = QPushButton("Open Quick Guide")
    help_button.clicked.connect(lambda: show_instructions_dialog(mw, addon_name))
    advanced_layout.addWidget(help_button)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    dialog_layout.addWidget(buttons)

    if dialog.exec() != QDialog.DialogCode.Accepted:
        return

    serialized_solution_fields = []
    translation_name = translation_field.currentText().strip() or config.dictionary_field or "Back"
    audio_name = str(audio_field.currentData() or "").strip()
    translation_label = (
        str(base_solution_state["translation_label"] or "")
        if translation_name == base_solution_state["translation_field"]
        else ""
    )
    combined_audio = bool(audio_name and audio_name == translation_name)
    serialized_solution_fields.append(
        {
            "field": translation_name,
            "label": translation_label,
            "display": "auto",
            "autoplay": combined_audio and bool(base_solution_state["audio_autoplay"]),
        }
    )
    if audio_name and not combined_audio:
        serialized_solution_fields.append(
            {
                "field": audio_name,
                "label": "",
                "display": "audio",
                "autoplay": bool(base_solution_state["audio_autoplay"]),
            }
        )
    for row in solution_rows:
        field_name = row["field"].currentText().strip()
        if not field_name:
            continue
        serialized_solution_fields.append(
            {
                "field": field_name,
                "label": row["label"].text().strip(),
                "display": row["display"].currentData() or "auto",
                "autoplay": row["autoplay"].isChecked(),
            }
        )
    compatibility_dictionary_field = translation_name

    saved_settings = {
        "deck_scope": "current",
        "deck_name": "",
        "custom_search_query": custom_search_query.text().strip()
        or DEFAULT_CONFIG["custom_search_query"],
        "target_field": target_field.currentText().strip() or "Front",
        "dictionary_field": compatibility_dictionary_field,
        "solution_fields": serialized_solution_fields,
        "included_card_templates": included_card_templates.text().strip(),
        "require_target_on_question": require_target_on_question.isChecked(),
        "language": str(language.currentData() or language.currentText()).strip() or "en",
        "native_language": native_language.text().strip() or "en",
        "matching_mode": matching_mode.currentData(),
        "target_extraction_mode": target_extraction.currentData(),
        "ignored_target_words": ignored_target_words.text().strip(),
        "database_path": database_path.text().strip() or DEFAULT_CONFIG["database_path"],
        "dictionary_url_template": dictionary_url.text().strip(),
        "min_sentence_words": min_words.value(),
        "max_sentence_words": max_words.value(),
        "max_due_cards": max_due.value(),
        "max_imported_sentences": library_target.value(),
        "future_due_days": future_due_days.value(),
        "font_size": font_size.value(),
        "include_due_cards": include_due.isChecked(),
        "include_new_cards": include_new.isChecked(),
        "max_new_cards": max_new.value(),
        "include_learning_cards": include_learning.isChecked(),
        "strict_import_filter": strict_import.isChecked(),
        "keep_downloaded_archives": keep_downloads.isChecked(),
    }

    profile_settings = dict(saved_settings)
    profile_settings["name"] = target_deck_name
    profile_settings["match"] = "subdeck"
    raw = upsert_deck_config(raw, target_deck_name, profile_settings)
    message = (
        "Contextual Review settings saved for:\n\n%s\n\n"
        "Select this deck, then use the Sentence Library, Diagnostics, or Start Review."
    ) % target_deck_name

    mw.addonManager.writeConfig(addon_name, raw)
    showInfo(message)


def show_diagnostics_dialog(mw: Any, addon_name: str) -> None:  # pragma: no cover - Anki UI
    from aqt.utils import showInfo, showWarning

    report = collect_diagnostics(mw, addon_name)
    message = format_diagnostics(report)
    if report.needs_attention:
        showWarning(message)
    else:
        showInfo(message)


def show_instructions_dialog(mw: Any, addon_name: str) -> None:  # pragma: no cover - Anki UI
    from aqt.qt import QDialog, QDialogButtonBox, QTextBrowser, QVBoxLayout

    dialog = QDialog(mw)
    dialog.setWindowTitle("Contextual Review Quick Guide")
    dialog.resize(760, 640)
    layout = QVBoxLayout(dialog)

    guide = QTextBrowser()
    guide.setHtml(INSTRUCTIONS_HTML)
    guide.setOpenExternalLinks(True)
    layout.addWidget(guide)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    settings = buttons.addButton("Open Settings", QDialogButtonBox.ButtonRole.ActionRole)
    settings.clicked.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    if dialog.exec() == QDialog.DialogCode.Accepted:
        open_settings_dialog(mw, addon_name)


def show_favorite_sentences_dialog(mw: Any, addon_name: str) -> None:  # pragma: no cover - Anki UI
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QListWidget,
        QPushButton,
        QTextBrowser,
        QVBoxLayout,
    )

    config = load_config(mw, addon_name)
    try:
        favorites_database_path = resolve_database_path(config)
    except Exception:
        favorites_database_path = None
    profile = load_language_profiles().get(config.language)
    language_name = profile.name if profile and profile.name else config.language.upper()

    dialog = QDialog(mw)
    dialog.setWindowTitle("Favorite Sentences: %s" % language_name)
    dialog.resize(820, 560)
    layout = QVBoxLayout(dialog)
    content = QHBoxLayout()
    sentence_list = QListWidget()
    details = QTextBrowser()
    content.addWidget(sentence_list, 2)
    content.addWidget(details, 3)
    layout.addLayout(content, 1)

    saved: list[Dict[str, Any]] = []

    def render_selected() -> None:
        index = sentence_list.currentRow()
        if index < 0 or index >= len(saved):
            details.setHtml("<p>Select a favorite sentence to review it.</p>")
            return
        item = saved[index]
        target_rows = "".join(
            "<li><b>%s</b>%s</li>"
            % (
                _escape_html(word.get("word", "")),
                ": " + _escape_html(word.get("definition", ""))
                if word.get("definition")
                else "",
            )
            for word in item.get("target_words", [])
            if isinstance(word, dict)
        )
        translation = _escape_html(item.get("translation", "")) or "No stored translation."
        details.setHtml(
            "<h2>%s</h2><p><b>Translation:</b> %s</p>%s"
            % (
                _escape_html(item.get("text", "")),
                translation,
                "<h3>Target Words</h3><ul>%s</ul>" % target_rows if target_rows else "",
            )
        )

    def refresh() -> None:
        nonlocal saved
        saved = favorite_sentences(favorites_database_path, config.language)
        sentence_list.clear()
        for item in saved:
            sentence_list.addItem(str(item.get("text", "") or "Saved sentence"))
        if saved:
            sentence_list.setCurrentRow(0)
        else:
            details.setHtml(
                "<h2>No favorite sentences yet</h2>"
                "<p>Use the star button while reviewing this language deck to save one.</p>"
            )

    def remove_selected() -> None:
        index = sentence_list.currentRow()
        if index < 0 or index >= len(saved):
            return
        remove_favorite_sentence(str(saved[index].get("key", "")))
        refresh()

    sentence_list.currentRowChanged.connect(lambda _row: render_selected())
    refresh()

    buttons_row = QHBoxLayout()
    remove_button = QPushButton("Remove from Favorites")
    remove_button.clicked.connect(remove_selected)
    buttons_row.addWidget(remove_button)
    buttons_row.addStretch(1)
    layout.addLayout(buttons_row)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    dialog.exec()


def _run_background(mw: Any, title: str, work, done_message, after_done=None) -> None:
    from aqt.qt import QProgressDialog, Qt
    from aqt.utils import showInfo, showWarning

    progress = QProgressDialog(title, None, 0, 0, mw)
    progress.setWindowTitle("Contextual Review")
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.setMinimumDuration(0)
    progress.show()

    taskman = getattr(mw, "taskman", None)

    def update_progress(message: str, value: int) -> None:
        def apply() -> None:
            progress.setLabelText(message)

        if taskman and hasattr(taskman, "run_on_main"):
            taskman.run_on_main(apply)
            return
        apply()

    def on_done(future: Any) -> None:
        progress.close()
        try:
            result = future.result()
        except Exception as exc:
            showWarning("Contextual Review task failed:\n\n%s" % exc)
            return
        showInfo(done_message(result))
        if callable(after_done):
            after_done()

    if taskman and hasattr(taskman, "run_in_background"):
        taskman.run_in_background(lambda: work(update_progress), on_done)
        return

    try:
        result = work(update_progress)
    except Exception as exc:
        progress.close()
        showWarning("Contextual Review task failed:\n\n%s" % exc)
        return
    progress.close()
    showInfo(done_message(result))
    if callable(after_done):
        after_done()


def _corpus_import_done_message(result: Any) -> str:
    message = "Imported %s sentences into %s. Skipped %s rows." % (
        result.inserted,
        result.database_path,
        result.skipped,
    )
    if result.inserted:
        if getattr(result, "limit_reached", False):
            message += "\n\nStopped at the configured import limit of %s sentences." % result.limit
        return message + "\n\nNext: run Tools > Contextual Review > Diagnostics."
    return (
        message
        + "\n\nNo sentences were added. Check that the file contains sentences in a supported format "
        "(.txt, .srt, .tsv, .csv, or .bz2), that the language matches your settings, and that sentence "
        "length/strict import filtering are not excluding every row."
    )


def _tatoeba_import_done_message(result: Any) -> str:
    message = "Imported %s Tatoeba sentences into %s. Skipped %s rows." % (
        result.inserted,
        result.database_path,
        result.skipped,
    )
    if result.inserted:
        if getattr(result, "limit_reached", False):
            message += "\n\nStopped at the configured import limit of %s sentences." % result.limit
        message += "\n\nTatoeba imports stream by default and do not keep the compressed archive unless Keep downloaded archives is enabled."
        return message + "\n\nNext: run Tools > Contextual Review > Diagnostics."
    return (
        message
        + "\n\nNo Tatoeba sentences were added. Check the language code and your min/max sentence length settings."
    )


def _word_forms_import_done_message(result: Any) -> str:
    message = "Imported %s word-form mappings into %s. Skipped %s rows." % (
        result.inserted,
        result.database_path,
        result.skipped,
    )
    if result.inserted:
        return message + "\n\nNext: use Vocabulary matching > Lemma family if you want these mappings during review."
    return (
        message
        + "\n\nNo word-form mappings were added. Use two columns: sentence form first, base card word second."
    )


def delete_sentence_registry_file(config: Any) -> Tuple[Path, bool]:
    db_path = resolve_database_path(config)
    if db_path.suffix.lower() not in DATABASE_SUFFIXES:
        raise RuntimeError(
            "Refusing to delete %s because the configured database path does not look like a SQLite database file."
            % db_path
        )
    if db_path.is_dir():
        raise RuntimeError("Refusing to delete %s because it is a directory." % db_path)
    if not db_path.exists():
        return db_path, False
    db_path.unlink()
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            db_path.with_name(db_path.name + suffix).unlink()
        except FileNotFoundError:
            pass
    return db_path, True


def _raw_config(mw: Any, addon_name: str) -> Dict[str, Any]:
    try:
        return dict(mw.addonManager.getConfig(addon_name) or {})
    except Exception:
        return dict(DEFAULT_CONFIG)


def _global_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config.update({key: value for key, value in raw.items() if key != "deck_configs"})
    return config


def _deck_profile_choices(raw: Dict[str, Any]) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = []
    profiles = raw.get("deck_configs")
    if not isinstance(profiles, list):
        return choices
    for profile in profiles:
        if not isinstance(profile, dict):
            continue
        deck_name = _profile_primary_deck_name(profile)
        if not deck_name:
            continue
        label = deck_config_name(profile, deck_name)
        if label != deck_name:
            label = "%s (%s)" % (label, deck_name)
        choices.append((label, deck_name))
    return choices


def _profile_primary_deck_name(profile: Any) -> str:
    if not isinstance(profile, dict):
        return ""
    for key in ("deck_name", "deck", "deck_names", "decks"):
        value = profile.get(key)
        if isinstance(value, list):
            for item in value:
                cleaned = str(item or "").strip()
                if cleaned:
                    return cleaned
        else:
            cleaned = str(value or "").strip()
            if cleaned:
                return cleaned
    return ""


def _escape_html(value: Any) -> str:
    text = str(value or "")
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _deck_names(mw: Any):
    try:
        decks = mw.col.decks.all_names_and_ids()
        return [deck.name for deck in decks]
    except Exception:
        try:
            return [deck["name"] for deck in mw.col.decks.all()]
        except Exception:
            return []


def _available_note_fields(mw: Any, deck_scope: str = "current", deck_name: str = "") -> list[str]:
    fields: list[str] = []
    seen = set()

    def remember(names) -> None:
        for name in names:
            cleaned = str(name or "").strip()
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                fields.append(cleaned)

    query = ""
    if deck_scope == "configured" and deck_name.strip():
        query = 'deck:"%s"' % deck_name.strip().replace('"', '\\"')
    elif deck_scope == "current":
        selected = _selected_deck_name(mw)
        if selected:
            query = 'deck:"%s"' % selected.replace('"', '\\"')

    try:
        card_ids = list(mw.col.find_cards(query))[:300]
    except Exception:
        card_ids = []
    for card_id in card_ids:
        try:
            note = mw.col.get_card(card_id).note()
            remember(note.keys())
        except Exception:
            continue

    if not fields:
        try:
            models = mw.col.models.all()
        except Exception:
            models = []
        for model in models or []:
            for field in model.get("flds", []) if isinstance(model, dict) else []:
                if isinstance(field, dict):
                    remember([field.get("name", "")])
    return fields


def _selected_deck_name(mw: Any) -> str:
    try:
        deck = mw.col.decks.get(mw.col.decks.selected())
        return str(deck.get("name", "") or "")
    except Exception:
        return ""


def _editable_combo(items, current: str):
    from aqt.qt import QComboBox

    combo = QComboBox()
    combo.setEditable(True)
    for item in items:
        combo.addItem(str(item))
    combo.setEditText(str(current or ""))
    return combo


def _language_combo(current: str):
    from aqt.qt import QComboBox

    combo = QComboBox()
    profiles = load_language_profiles()
    for code, profile in sorted(
        profiles.items(), key=lambda item: (item[1].name or item[0]).casefold()
    ):
        combo.addItem("%s (%s)" % (profile.name or code.upper(), code), code)
    _set_combo_value(combo, current)
    if combo.findData(current) < 0:
        combo.addItem(str(current or "en"), str(current or "en"))
        _set_combo_value(combo, current)
    return combo


def _optional_combo(items, current: str, empty_label: str):
    from aqt.qt import QComboBox

    combo = QComboBox()
    combo.addItem(empty_label, "")
    seen = set()
    for item in items:
        value = str(item or "").strip()
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            combo.addItem(value, value)
    if current and combo.findData(current) < 0:
        combo.addItem(current, current)
    _set_optional_combo_value(combo, current)
    return combo


def _set_optional_combo_value(combo: Any, value: str) -> None:
    index = combo.findData(str(value or ""))
    combo.setCurrentIndex(index if index >= 0 else 0)


def _replace_optional_combo_items(combo: Any, items) -> None:
    current = str(combo.currentData() or "")
    empty_label = combo.itemText(0) if combo.count() else "None"
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(empty_label, "")
    for item in items:
        value = str(item or "").strip()
        if value and combo.findData(value) < 0:
            combo.addItem(value, value)
    if current and combo.findData(current) < 0:
        combo.addItem(current, current)
    _set_optional_combo_value(combo, current)
    combo.blockSignals(False)


def _basic_solution_fields(config: Any):
    """Split simple translation/audio mappings from additional advanced fields."""
    specs = list(getattr(config, "solution_fields", ()) or ())
    dictionary_field = str(getattr(config, "dictionary_field", "") or "").casefold()

    audio_index = next(
        (
            index
            for index, spec in enumerate(specs)
            if getattr(spec, "display", "auto") == "audio"
            or bool(getattr(spec, "autoplay", False))
        ),
        None,
    )
    translation_index = next(
        (
            index
            for index, spec in enumerate(specs)
            if index != audio_index
            and str(getattr(spec, "field", "") or "").casefold() == dictionary_field
        ),
        None,
    )
    if translation_index is None:
        translation_index = next(
            (
                index
                for index, spec in enumerate(specs)
                if index != audio_index
                and getattr(spec, "display", "auto") in {"auto", "text"}
            ),
            None,
        )

    translation = specs[translation_index] if translation_index is not None else None
    audio = specs[audio_index] if audio_index is not None else None
    claimed = {index for index in (translation_index, audio_index) if index is not None}
    extras = [spec for index, spec in enumerate(specs) if index not in claimed]
    return translation, audio, extras


def _replace_combo_items(combo: Any, items) -> None:
    current = combo.currentText()
    combo.blockSignals(True)
    combo.clear()
    for item in items:
        combo.addItem(str(item))
    combo.setEditText(current)
    combo.blockSignals(False)


def _spin(value: int, minimum: int, maximum: int):
    from aqt.qt import QSpinBox

    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setValue(value)
    return spin


def _set_combo_value(combo: Any, value: str) -> None:
    index = combo.findData(value)
    if index >= 0:
        combo.setCurrentIndex(index)
