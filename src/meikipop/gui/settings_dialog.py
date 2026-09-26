# meikipop/gui/settings_dialog.py
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QFontDatabase
from PyQt6.QtWidgets import (QWidget, QDialog, QFormLayout, QComboBox,
                             QSpinBox, QCheckBox, QPushButton, QColorDialog, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QDialogButtonBox, QLabel, QSlider, QDoubleSpinBox,
                             QTabWidget, QSizePolicy, QFontComboBox, QLineEdit, QFileDialog)

from meikipop.anki import ankiconnect
from meikipop.dictionary.lookup import Lookup
from meikipop.config.config import config, APP_NAME, IS_WINDOWS
from meikipop.gui.input import InputLoop
from meikipop.gui.popup import Popup
from meikipop.ocr.ocr import OcrProcessor

THEMES = {
    "JL": {
        "color_background": "#F6F6F6", "color_foreground": "#000000",
        "color_highlight_word": "#03A9F4", "color_highlight_reading": "#000000",
        "color_deconjugation": "#4CAF50", "color_frequency": "#FFFF00", "color_dictionary": "#ADD8E6",
        "background_opacity": 230,
    },
    "Nazeka": {
        "color_background": "#2E2E2E", "color_foreground": "#F0F0F0",
        "color_highlight_word": "#88D8FF", "color_highlight_reading": "#90EE90",
        "background_opacity": 245,
    },
    "Celestial Indigo": {
        "color_background": "#281E50", "color_foreground": "#EAEFF5",
        "color_highlight_word": "#D4C58A", "color_highlight_reading": "#B5A2D4",
        "background_opacity": 245,
    },
    "Neutral Slate": {
        "color_background": "#5D5C5B", "color_foreground": "#EFEBE8",
        "color_highlight_word": "#A3B8A3", "color_highlight_reading": "#A3B8A3",
        "background_opacity": 245,
    },
    "Academic": {
        "color_background": "#FDFBF7", "color_foreground": "#212121",
        "color_highlight_word": "#8C2121", "color_highlight_reading": "#005A9C",
        "background_opacity": 245,
    },
    "Custom": {}
}


class SettingsDialog(QDialog):
    def __init__(self, ocr_processor: OcrProcessor, popup_window: Popup, input_loop: InputLoop, lookup: Lookup,
                 tray_icon, parent=None):
        super().__init__(parent)
        self.ocr_processor = ocr_processor
        self.popup_window = popup_window
        self.input_loop = input_loop
        self.tray_icon = tray_icon
        self.lookup = lookup

        self.setWindowTitle(f"{APP_NAME} Settings")
        self.setWindowIcon(QIcon("icon.ico"))
        self.setMinimumWidth(400)

        # Keep track of all form layouts to unify their spacing later
        self.form_layouts = []

        # Main vertical layout for the Dialog
        main_layout = QVBoxLayout(self)

        # Create the Tab Widget
        self.tabs = QTabWidget()

        # ==========================================
        # TAB 1: General
        # ==========================================
        self.tab_general = QWidget()
        self.tab_general_layout = QVBoxLayout(self.tab_general)

        # --- Group 1: Core Settings ---
        core_group = QGroupBox("Core Settings")
        core_layout = QFormLayout()
        self.form_layouts.append(core_layout)

        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(['ctrl', 'shift', 'alt', 'ctrl+shift', 'ctrl+alt', 'shift+alt', 'ctrl+shift+alt'])
        self.hotkey_combo.setCurrentText(config.hotkey)
        self._set_expanding(self.hotkey_combo)
        core_layout.addRow("Hotkey:", self.hotkey_combo)

        self.ocr_provider_combo = QComboBox()
        self.ocr_provider_combo.addItems(self.ocr_processor.available_providers.keys())
        self.ocr_provider_combo.setCurrentText(config.ocr_provider)
        self.ocr_provider_combo.currentTextChanged.connect(self._update_glens_state)
        self._set_expanding(self.ocr_provider_combo)
        core_layout.addRow("OCR Provider:", self.ocr_provider_combo)

        # Google Lens specific option
        self.glens_compression_check_label = QLabel("Google Lens Compression:")
        self.glens_compression_check = QCheckBox()
        self.glens_compression_check.setChecked(config.glens_low_bandwidth)
        self.glens_compression_check.setToolTip(
            "Compresses screenshots before sending them to Google Lens\nSignificantly improves ocr latency on slow internet connections, but slightly worsens ocr accuracy and system load"
        )
        core_layout.addRow(self.glens_compression_check_label, self.glens_compression_check)

        self.max_lookup_spin = QSpinBox()
        self.max_lookup_spin.setRange(5, 100)
        self.max_lookup_spin.setValue(config.max_lookup_length)
        core_layout.addRow("Max Lookup Length:", self.max_lookup_spin)

        freq_container = QWidget()
        freq_row = QHBoxLayout(freq_container)
        freq_row.setContentsMargins(0, 0, 0, 0)
        self.freq_path_edit = QLineEdit(config.frequency_list_path)
        self.freq_path_edit.setPlaceholderText("meikipop's own (jiten.moe)")
        self.freq_path_edit.setToolTip("A Nazeka-format frequency list, e.g. JL's Resources\\freqlist_vns.json, "
                                       "to show the same frequency numbers as JL")
        freq_browse = QPushButton("Browse…")
        freq_browse.clicked.connect(self._browse_frequency_list)
        freq_row.addWidget(self.freq_path_edit)
        freq_row.addWidget(freq_browse)
        core_layout.addRow("Frequency List:", freq_container)

        if IS_WINDOWS:
            self.magpie_check = QCheckBox()
            self.magpie_check.setChecked(config.magpie_compatibility)
            self.magpie_check.setToolTip("Enable transformations for compatibility with Magpie game scaler.")
            core_layout.addRow("Magpie Compatibility:", self.magpie_check)

        core_group.setLayout(core_layout)
        self.tab_general_layout.addWidget(core_group)

        # --- Group 2: Auto Scan Mode ---
        auto_group = QGroupBox("Auto Scan Mode")
        auto_layout = QFormLayout()
        self.form_layouts.append(auto_layout)

        self.auto_scan_check = QCheckBox()
        self.auto_scan_check.setChecked(config.auto_scan_mode)
        self.auto_scan_check.setToolTip(
            "Permanently ocr screen region\nImproves perceived latency, but worsens system load")
        self.auto_scan_check.toggled.connect(self._update_auto_scan_state)
        auto_layout.addRow("Enable Auto Scan:", self.auto_scan_check)

        self.auto_scan_mouse_move_check_label = QLabel("Only Scan on Mouse Move:")
        self.auto_scan_mouse_move_check = QCheckBox()
        self.auto_scan_mouse_move_check.setChecked(config.auto_scan_on_mouse_move)
        self.auto_scan_mouse_move_check.setToolTip(
            "Prevents auto ocr to occur, if mouse is not moved\nCan reduce system load, but worsen perceived latency")
        auto_layout.addRow(self.auto_scan_mouse_move_check_label, self.auto_scan_mouse_move_check)

        self.auto_scan_interval_spin_label = QLabel("Scan Interval (Cooldown):")
        self.auto_scan_interval_spin = QDoubleSpinBox()
        self.auto_scan_interval_spin.setRange(0.0, 60.0)
        self.auto_scan_interval_spin.setDecimals(1)
        self.auto_scan_interval_spin.setSingleStep(0.1)
        self.auto_scan_interval_spin.setValue(config.auto_scan_interval_seconds)
        self.auto_scan_interval_spin.setSuffix(" s")
        self.auto_scan_interval_spin.setToolTip(
            "Prevents auto ocr to occur with a high frequency\nCan reduce system load, but worsens perceived latency")
        auto_layout.addRow(self.auto_scan_interval_spin_label, self.auto_scan_interval_spin)

        self.auto_scan_no_hotkey_check_label = QLabel("Show Popup without Hotkey:")
        self.auto_scan_no_hotkey_check = QCheckBox()
        self.auto_scan_no_hotkey_check.setChecked(config.auto_scan_mode_lookups_without_hotkey)
        auto_layout.addRow(self.auto_scan_no_hotkey_check_label, self.auto_scan_no_hotkey_check)

        auto_group.setLayout(auto_layout)
        self.tab_general_layout.addWidget(auto_group)

        # --- Group 3: Popup Behavior ---
        behavior_group = QGroupBox("Popup Behavior")
        behavior_layout = QFormLayout()
        self.form_layouts.append(behavior_layout)

        self.popup_position_combo = QComboBox()
        self.popup_position_combo.addItems(["Always Below Cursor", "Flip Both", "Flip Vertically", "Flip Horizontally", "Visual Novel Mode"])
        self.popup_mode_map = {
            "Always Below Cursor": "always_below",
            "Flip Both": "flip_both",
            "Flip Vertically": "flip_vertically",
            "Flip Horizontally": "flip_horizontally",
            "Visual Novel Mode": "visual_novel_mode"
        }
        current_friendly_name = next(
            (k for k, v in self.popup_mode_map.items() if v == config.popup_position_mode), "Flip Vertically"
        )
        self.popup_position_combo.setCurrentText(current_friendly_name)
        self._set_expanding(self.popup_position_combo)
        behavior_layout.addRow("Position Mode:", self.popup_position_combo)

        self.max_width_spin = QSpinBox()
        self.max_width_spin.setRange(10, 100)
        self.max_width_spin.setSuffix(" % of screen")
        self.max_width_spin.setValue(config.popup_max_width_percent)
        behavior_layout.addRow("Max Popup Width:", self.max_width_spin)

        self.max_height_spin = QSpinBox()
        self.max_height_spin.setRange(0, 100)
        self.max_height_spin.setSuffix(" % of screen")
        self.max_height_spin.setSpecialValueText("No limit")
        self.max_height_spin.setValue(config.popup_max_height_percent)
        behavior_layout.addRow("Max Popup Height:", self.max_height_spin)

        self.compact_check = QCheckBox()
        self.compact_check.setChecked(config.compact_mode)
        behavior_layout.addRow("Compact Mode:", self.compact_check)

        behavior_group.setLayout(behavior_layout)
        self.tab_general_layout.addWidget(behavior_group)
        self.tab_general_layout.addStretch()

        # ==========================================
        # TAB 2: Popup Content
        # ==========================================
        self.tab_content = QWidget()
        self.tab_content_layout = QVBoxLayout(self.tab_content)

        # --- Group 1: Vocab Entry Content ---
        vocab_group = QGroupBox("Vocab Entry Content")
        vocab_layout = QFormLayout()
        self.form_layouts.append(vocab_layout)

        self.show_glosses_check = QCheckBox()
        self.show_glosses_check.setChecked(config.show_all_glosses)
        vocab_layout.addRow("Show All Glosses:", self.show_glosses_check)

        self.show_deconj_check = QCheckBox()
        self.show_deconj_check.setChecked(config.show_deconjugation)
        vocab_layout.addRow("Show Deconjugation:", self.show_deconj_check)

        self.show_pos_check = QCheckBox()
        self.show_pos_check.setChecked(config.show_pos)
        vocab_layout.addRow("Show Part of Speech:", self.show_pos_check)

        self.show_tags_check = QCheckBox()
        self.show_tags_check.setChecked(config.show_tags)
        vocab_layout.addRow("Show Tags:", self.show_tags_check)

        self.show_frequency_check = QCheckBox()
        self.show_frequency_check.setChecked(config.show_frequency)
        vocab_layout.addRow("Show Frequency:", self.show_frequency_check)

        vocab_group.setLayout(vocab_layout)
        self.tab_content_layout.addWidget(vocab_group)

        # --- Group 2: Kanji Entry Content ---
        kanji_group = QGroupBox("Kanji Entry Content")
        kanji_layout = QFormLayout()
        self.form_layouts.append(kanji_layout)

        self.show_kanji_check = QCheckBox()
        self.show_kanji_check.setChecked(config.show_kanji)
        self.show_kanji_check.toggled.connect(self._update_kanji_options_state)
        kanji_layout.addRow("Show Kanji Entries:", self.show_kanji_check)

        self.show_examples_check = QCheckBox()
        self.show_examples_check.setChecked(config.show_examples)
        kanji_layout.addRow("Show Examples:", self.show_examples_check)

        self.show_components_check = QCheckBox()
        self.show_components_check.setChecked(config.show_components)
        kanji_layout.addRow("Show Components:", self.show_components_check)

        kanji_group.setLayout(kanji_layout)
        self.tab_content_layout.addWidget(kanji_group)
        self.tab_content_layout.addStretch()

        # ==========================================
        # TAB 3: Popup Appearance
        # ==========================================
        self.tab_appearance = QWidget()
        self.tab_appearance_layout = QVBoxLayout(self.tab_appearance)

        # --- Group 1: Theme ---
        theme_group = QGroupBox("Theme")
        theme_layout = QFormLayout()
        self.form_layouts.append(theme_layout)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.setCurrentText(config.theme_name if config.theme_name in THEMES else "Custom")
        self.theme_combo.currentTextChanged.connect(self._apply_theme)
        self._set_expanding(self.theme_combo)
        theme_layout.addRow("Preset:", self.theme_combo)

        self.layout_combo = QComboBox()
        self.layout_map = {"JL": "jl", "meikipop": "classic"}
        self.layout_combo.addItems(self.layout_map.keys())
        self.layout_combo.setCurrentText(next((k for k, v in self.layout_map.items() if v == config.popup_layout), "JL"))
        self.layout_combo.setToolTip("JL: word, reading, conjugation and frequency on one line, then one line per "
                                     "meaning with all glosses (ignores the compact/gloss/part-of-speech toggles)")
        self._set_expanding(self.layout_combo)
        theme_layout.addRow("Layout:", self.layout_combo)

        self.opacity_slider_container = QWidget()
        opacity_layout = QHBoxLayout(self.opacity_slider_container)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 255)
        self.opacity_slider.setValue(config.background_opacity)
        self.opacity_label = QLabel(f"{config.background_opacity}")
        self.opacity_label.setMinimumWidth(30)
        self.opacity_slider.valueChanged.connect(lambda val: self.opacity_label.setText(str(val)))
        self.opacity_slider.valueChanged.connect(self._mark_as_custom)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_label)
        theme_layout.addRow("Background Opacity:", self.opacity_slider_container)

        theme_group.setLayout(theme_layout)
        self.tab_appearance_layout.addWidget(theme_group)

        # --- Group 2: Typography ---
        typo_group = QGroupBox("Typography")
        typo_layout = QFormLayout()
        self.form_layouts.append(typo_layout)

        self.font_family_combo = QFontComboBox()
        self.font_family_combo.setWritingSystem(QFontDatabase.WritingSystem.Japanese)
        self._set_expanding(self.font_family_combo)
        default_font_name = self.font().family()
        if self.font_family_combo.findText(default_font_name) == -1:
            self.font_family_combo.insertItem(0, default_font_name)
        target_font_name = config.font_family if config.font_family else default_font_name
        index = self.font_family_combo.findText(target_font_name)
        if index != -1:
            self.font_family_combo.setCurrentIndex(index)
        else:
            self.font_family_combo.setCurrentText(default_font_name)
        typo_layout.addRow("Font Family:", self.font_family_combo)

        self.font_size_header_spin = QSpinBox()
        self.font_size_header_spin.setRange(8, 72)
        self.font_size_header_spin.setValue(config.font_size_header)
        typo_layout.addRow("Font Size (Header):", self.font_size_header_spin)

        self.font_size_def_spin = QSpinBox()
        self.font_size_def_spin.setRange(8, 72)
        self.font_size_def_spin.setValue(config.font_size_definitions)
        typo_layout.addRow("Font Size (Definitions):", self.font_size_def_spin)

        typo_group.setLayout(typo_layout)
        self.tab_appearance_layout.addWidget(typo_group)

        # --- Group 3: Colors ---
        color_group = QGroupBox("Colors")
        color_layout = QFormLayout()
        self.form_layouts.append(color_layout)

        self.color_widgets = {}
        color_settings_map = {"Background": "color_background", "Foreground": "color_foreground",
                              "Highlight Word": "color_highlight_word", "Highlight Reading": "color_highlight_reading",
                              "Conjugation (JL layout)": "color_deconjugation", "Frequency (JL layout)": "color_frequency",
                              "Dictionary Name (JL layout)": "color_dictionary"}
        for name, key in color_settings_map.items():
            btn = QPushButton(getattr(config, key))
            btn.clicked.connect(lambda _, k=key, b=btn: self.pick_color(k, b))
            self.color_widgets[key] = btn
            color_layout.addRow(f"{name}:", btn)

        color_group.setLayout(color_layout)
        self.tab_appearance_layout.addWidget(color_group)
        self.tab_appearance_layout.addStretch()

        # ==========================================
        # TAB 4: Anki
        # ==========================================
        self.tab_anki = QWidget()
        self.tab_anki_layout = QVBoxLayout(self.tab_anki)

        anki_group = QGroupBox("Anki Mining")
        anki_layout = QFormLayout()
        self.form_layouts.append(anki_layout)

        self.anki_enabled_check = QCheckBox()
        self.anki_enabled_check.setChecked(config.anki_enabled)
        anki_layout.addRow("Enable Mining:", self.anki_enabled_check)

        self.anki_url_edit = QLineEdit(config.anki_connect_url)
        anki_layout.addRow("AnkiConnect URL:", self.anki_url_edit)

        self.anki_deck_combo = QComboBox()
        self.anki_deck_combo.setEditable(True)
        self.anki_deck_combo.setCurrentText(config.anki_deck)
        self._set_expanding(self.anki_deck_combo)
        anki_layout.addRow("Deck:", self.anki_deck_combo)

        self.anki_model_combo = QComboBox()
        self.anki_model_combo.setEditable(True)
        self.anki_model_combo.setCurrentText(config.anki_note_type)
        self._set_expanding(self.anki_model_combo)
        anki_layout.addRow("Note Type:", self.anki_model_combo)

        self.anki_tags_edit = QLineEdit(config.anki_tags)
        self.anki_tags_edit.setPlaceholderText("space separated")
        anki_layout.addRow("Tags:", self.anki_tags_edit)

        self.anki_duplicates_check = QCheckBox()
        self.anki_duplicates_check.setChecked(config.anki_allow_duplicates)
        anki_layout.addRow("Allow Duplicates:", self.anki_duplicates_check)

        self.anki_refresh_button = QPushButton("Load Decks && Note Types from Anki")
        self.anki_refresh_button.clicked.connect(self._refresh_anki)
        anki_layout.addRow(self.anki_refresh_button)
        self.anki_status_label = QLabel("")
        self.anki_status_label.setWordWrap(True)
        anki_layout.addRow(self.anki_status_label)

        anki_group.setLayout(anki_layout)
        self.tab_anki_layout.addWidget(anki_group)

        self.anki_fields_group = QGroupBox("Fields")
        self.anki_fields_layout = QFormLayout()
        self.anki_fields_group.setLayout(self.anki_fields_layout)
        self.tab_anki_layout.addWidget(self.anki_fields_group)
        self.anki_field_combos = {}
        self._build_anki_field_rows(ankiconnect.parse_field_map(config.anki_fields))

        hint = QLabel("Middle click an open popup to lock it, then click an entry to add it to Anki. "
                      "Esc, middle click or clicking elsewhere closes it.")
        hint.setWordWrap(True)
        self.tab_anki_layout.addWidget(hint)
        self.tab_anki_layout.addStretch()

        self.anki_model_combo.currentTextChanged.connect(self._on_anki_model_changed)
        self._anki_loaded = False
        self.tabs.currentChanged.connect(
            lambda i: self._refresh_anki() if self.tabs.widget(i) is self.tab_anki and not self._anki_loaded else None)

        # Add tabs to main layout
        self.tabs.addTab(self.tab_general, "General")
        self.tabs.addTab(self.tab_content, "Popup Content")
        self.tabs.addTab(self.tab_appearance, "Popup Appearance")
        self.tabs.addTab(self.tab_anki, "Anki")
        main_layout.addWidget(self.tabs)

        # Buttons
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

        # Calculate Layout Alignment
        self._finalize_layout_styling()

        # Initialize UI States
        self._update_color_buttons()
        self._update_auto_scan_state(self.auto_scan_check.isChecked())
        self._update_glens_state(self.ocr_provider_combo.currentText())
        self._update_kanji_options_state(self.show_kanji_check.isChecked())

    def _browse_frequency_list(self):
        path, _ = QFileDialog.getOpenFileName(self, "Frequency list (Nazeka format)", self.freq_path_edit.text(),
                                              "JSON (*.json)")
        if path:
            self.freq_path_edit.setText(path)

    # --- Anki tab ---
    def _current_anki_field_map(self):
        return {name: combo.currentData() for name, combo in self.anki_field_combos.items()}

    def _build_anki_field_rows(self, field_map):
        while self.anki_fields_layout.rowCount():
            self.anki_fields_layout.removeRow(0)
        self.anki_field_combos = {}
        for field_name, content in field_map.items():
            combo = QComboBox()
            for key, label in ankiconnect.FIELD_CONTENT_TYPES.items():
                combo.addItem(label, key)
            combo.setCurrentIndex(max(0, combo.findData(content)))
            self._set_expanding(combo)
            self.anki_fields_layout.addRow(f"{field_name}:", combo)
            self.anki_field_combos[field_name] = combo

    def _with_anki_url(self, func, *args):
        # the url field may not be saved yet
        saved_url = config.anki_connect_url
        config.anki_connect_url = self.anki_url_edit.text().strip()
        try:
            return func(*args)
        finally:
            config.anki_connect_url = saved_url

    def _refresh_anki(self):
        self._anki_loaded = True
        try:
            decks = self._with_anki_url(ankiconnect.deck_names)
            models = self._with_anki_url(ankiconnect.model_names)
        except ankiconnect.AnkiError as e:
            self.anki_status_label.setText(str(e))
            return
        for combo, items in ((self.anki_deck_combo, decks), (self.anki_model_combo, models)):
            current = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(sorted(items))
            combo.setCurrentText(current)
            combo.blockSignals(False)
        self.anki_status_label.setText(f"Connected to Anki: {len(decks)} decks, {len(models)} note types.")
        self._on_anki_model_changed(self.anki_model_combo.currentText())

    def _on_anki_model_changed(self, model_name):
        try:
            field_names = self._with_anki_url(ankiconnect.model_field_names, model_name)
        except ankiconnect.AnkiError:
            return
        current = self._current_anki_field_map()
        self._build_anki_field_rows({name: current.get(name, 'nothing') for name in field_names})

    def _set_expanding(self, widget):
        """Helper to let a widget expand horizontally"""
        widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _finalize_layout_styling(self):
        """ Sets all label columns to that width to align the controls perfectly"""
        max_label_width = 0

        # Pass 1: Measure largest label
        for layout in self.form_layouts:
            for i in range(layout.rowCount()):
                item = layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
                if item and item.widget():
                    max_label_width = max(max_label_width, item.widget().sizeHint().width())

        # Add a little padding to be safe
        max_label_width += 5

        # Pass 2: Apply width and standard styling
        for layout in self.form_layouts:
            # Important: AllNonFixedFieldsGrow ensures combo boxes fill the space
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            layout.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
            layout.setHorizontalSpacing(15)  # Unified gap size

            for i in range(layout.rowCount()):
                item = layout.itemAt(i, QFormLayout.ItemRole.LabelRole)
                if item and item.widget():
                    item.widget().setMinimumWidth(max_label_width)

    def _update_auto_scan_state(self, is_checked):
        """Grays out auto scan options if the main toggle is off."""
        self.auto_scan_interval_spin.setEnabled(is_checked)
        self.auto_scan_no_hotkey_check.setEnabled(is_checked)
        self.auto_scan_mouse_move_check.setEnabled(is_checked)
        self.auto_scan_interval_spin_label.setEnabled(is_checked)
        self.auto_scan_no_hotkey_check_label.setEnabled(is_checked)
        self.auto_scan_mouse_move_check_label.setEnabled(is_checked)

    def _update_glens_state(self, current_provider):
        """Grays out Google Lens options if another provider is selected."""
        is_glens = "Google Lens (remote)" in current_provider
        self.glens_compression_check.setEnabled(is_glens)
        self.glens_compression_check_label.setEnabled(is_glens)

    def _update_kanji_options_state(self, is_checked):
        """Enables/Disables kanji specific sub-options."""
        self.show_examples_check.setEnabled(is_checked)
        self.show_components_check.setEnabled(is_checked)
        self.lookup.clear_cache()

    def _mark_as_custom(self):
        if self.theme_combo.currentText() != "Custom":
            self.theme_combo.setCurrentText("Custom")

    def _apply_theme(self, theme_name):
        if theme_name in THEMES and theme_name != "Custom":
            theme_data = THEMES[theme_name]
            for key, value in theme_data.items():
                setattr(config, key, value)
            self._update_color_buttons()
            self.opacity_slider.setValue(config.background_opacity)

    def _update_color_buttons(self):
        for key, btn in self.color_widgets.items():
            color_hex = getattr(config, key)
            btn.setText(color_hex)
            q_color = QColor(color_hex)
            text_color = "#000000" if q_color.lightness() > 127 else "#FFFFFF"
            btn.setStyleSheet(f"background-color: {color_hex}; color: {text_color};")

    def pick_color(self, key, btn):
        color = QColorDialog.getColor(QColor(getattr(config, key)), self)
        if color.isValid():
            setattr(config, key, color.name())
            self._update_color_buttons()
            self._mark_as_custom()

    def save_and_accept(self):
        # Update OCR Provider
        selected_provider = self.ocr_provider_combo.currentText()
        if selected_provider != config.ocr_provider:
            self.ocr_processor.switch_provider(selected_provider)

        # Update all other config values
        config.hotkey = self.hotkey_combo.currentText()
        config.glens_low_bandwidth = self.glens_compression_check.isChecked()
        config.max_lookup_length = self.max_lookup_spin.value()
        config.frequency_list_path = self.freq_path_edit.text().strip()
        config.anki_enabled = self.anki_enabled_check.isChecked()
        config.anki_connect_url = self.anki_url_edit.text().strip()
        config.anki_deck = self.anki_deck_combo.currentText()
        config.anki_note_type = self.anki_model_combo.currentText()
        config.anki_tags = self.anki_tags_edit.text().strip()
        config.anki_allow_duplicates = self.anki_duplicates_check.isChecked()
        config.anki_fields = ankiconnect.format_field_map(self._current_anki_field_map())
        config.auto_scan_mode = self.auto_scan_check.isChecked()
        config.auto_scan_interval_seconds = self.auto_scan_interval_spin.value()
        config.auto_scan_mode_lookups_without_hotkey = self.auto_scan_no_hotkey_check.isChecked()
        config.auto_scan_on_mouse_move = self.auto_scan_mouse_move_check.isChecked()

        if IS_WINDOWS:
            config.magpie_compatibility = self.magpie_check.isChecked()
        config.compact_mode = self.compact_check.isChecked()
        config.show_all_glosses = self.show_glosses_check.isChecked()
        config.show_deconjugation = self.show_deconj_check.isChecked()
        config.show_pos = self.show_pos_check.isChecked()
        config.show_tags = self.show_tags_check.isChecked()
        config.show_frequency = self.show_frequency_check.isChecked()
        config.show_kanji = self.show_kanji_check.isChecked()
        config.show_examples = self.show_examples_check.isChecked()
        config.show_components = self.show_components_check.isChecked()

        selected_friendly_name = self.popup_position_combo.currentText()
        config.popup_position_mode = self.popup_mode_map.get(selected_friendly_name, "flip_vertically")
        config.popup_max_width_percent = self.max_width_spin.value()
        config.popup_max_height_percent = self.max_height_spin.value()
        config.theme_name = self.theme_combo.currentText()
        config.popup_layout = self.layout_map.get(self.layout_combo.currentText(), "jl")
        config.background_opacity = self.opacity_slider.value()
        config.font_family = self.font_family_combo.currentFont().family()
        config.font_size_header = self.font_size_header_spin.value()
        config.font_size_definitions = self.font_size_def_spin.value()
        config.save()

        # Tell the live components to re-apply settings
        self.input_loop.reapply_settings()
        self.popup_window.reapply_settings()
        self.tray_icon.reapply_settings()
        self.ocr_processor.shared_state.screenshot_trigger_event.set()

        self.accept()