# meikipop/gui/popup.py
import html
import logging
import threading
from typing import List, Optional

from PyQt6.QtCore import QTimer, QPoint, QSize, QEvent, pyqtSignal
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QFontInfo
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QApplication, QScrollArea

from meikipop.anki import ankiconnect
from meikipop.config.config import config, IS_MACOS, IS_WINDOWS
from meikipop.dictionary import freqlist
from meikipop.dictionary.lookup import DictionaryEntry, KanjiEntry
from meikipop.gui.magpie_manager import magpie_manager

# macOS-specific imports for focus management
if IS_MACOS:
    try:
        import Quartz
    except ImportError:
        Quartz = None

logger = logging.getLogger(__name__)

MARK_PLACEHOLDER = '<!--mark-->'  # where a mined entry gets its ✓
SCROLLBAR_WIDTH = 8
MINED_COLORS = {'added': '#5FD35F', 'duplicate': '#FF6B6B'}  # fixed so they read the same in every theme


class Popup(QWidget):
    # emitted from the input hook threads, handled on the gui thread
    lock_toggle_requested = pyqtSignal()
    click_while_locked = pyqtSignal()
    escape_pressed = pyqtSignal()
    mine_click_requested = pyqtSignal()  # windows: left click inside the locked popup, seen by the mouse hook
    scroll_requested = pyqtSignal(int)  # windows: wheel delta inside the locked popup
    _mine_finished = pyqtSignal(int, str, str)  # entry index, status, message

    def __init__(self, shared_state, input_loop):
        super().__init__()
        self._latest_data = None
        self._latest_context = None
        self._context = None  # (paragraph text, char index) of the lookup being shown
        self._last_latest_data = None
        self._data_lock = threading.Lock()
        self._previous_active_window_on_mac = None

        self.shared_state = shared_state
        self.input_loop = input_loop
        input_loop.attach_popup(self)

        # mining mode: middle click locks the popup in place, clicking a headword adds it to anki
        self.locked = False
        self._mined = {}  # entry index -> 'pending' | 'added' | 'duplicate' | 'failed'
        self.lock_toggle_requested.connect(self.toggle_lock)
        self.click_while_locked.connect(self._on_click_while_locked)
        self.escape_pressed.connect(self.unlock)
        self.mine_click_requested.connect(self._on_mine_click)
        self.scroll_requested.connect(self._on_scroll)
        self.native_handle = None  # hwnd, read by the input hook thread
        self._mine_finished.connect(self._on_mine_finished)

        self.is_visible = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_latest_data_loop)
        self.timer.start(10)

        self.probe_label = QLabel()
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextFormat(Qt.TextFormat.RichText)

        self.is_calibrated = False
        self.header_chars_per_line = 50
        self.def_chars_per_line = 50

        # per-lookup layout, so the popup can drop trailing entries to fit a height limit
        self._entries = []
        self._entry_htmls = []
        self._entry_heights = []  # content height when showing the first n+1 entries
        self._content_width = 0
        self._shown = None  # (entry count, height) currently displayed

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool |
            Qt.WindowType.WindowDoesNotAcceptFocus |  # clicking it to mine must not take focus from the game
            Qt.WindowType.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame()
        self._apply_frame_stylesheet()
        main_layout.addWidget(self.frame)

        self.content_layout = QVBoxLayout(self.frame)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.display_label = QLabel()
        self.display_label.setWordWrap(True)
        self.display_label.setTextFormat(Qt.TextFormat.RichText)
        # if a single entry is taller than the allowed height, clip its bottom rather than its middle
        self.display_label.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        # clicking anywhere on an entry mines it (only while locked)
        self.display_label.installEventFilter(self)

        # scrolling is only turned on while locked, when all entries are shown
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.display_label)
        self.content_layout.addWidget(self.scroll_area)

        self.footer_label = QLabel()
        self.footer_label.setWordWrap(True)
        self.footer_label.hide()
        self.content_layout.addWidget(self.footer_label)

        self.hide()

    def _apply_frame_stylesheet(self):
        bg_color = QColor(config.color_background)
        r, g, b = bg_color.red(), bg_color.green(), bg_color.blue()
        a = config.background_opacity
        self.probe_label.setFont(QFont(config.font_family))
        self.frame.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({r}, {g}, {b}, {a});
                color: {config.color_foreground};
                border-radius: 8px;
                border: 1px solid #555;
            }}
            QLabel {{
                background-color: transparent;
                border: none;
                font-family: "{config.font_family}";
            }}
            QScrollArea, QScrollArea > QWidget > QWidget {{
                background-color: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: {SCROLLBAR_WIDTH}px;
                margin: 0px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(128, 128, 128, 160);
                border-radius: {SCROLLBAR_WIDTH // 2}px;
                min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: none;
            }}
            hr {{
                border: none;
                height: 1px;
            }}
        """)

    def _calibrate_empirically(self):
        logger.debug("--- Calibrating Font Metrics Empirically (One-Time) ---")

        # Log font info
        actual_font = self.display_label.font()
        font_info = QFontInfo(actual_font)
        logger.debug(f"[FONT DEBUG] Requested font family: '{config.font_family}' (or default)")
        logger.debug(f"[FONT DEBUG]   -> Actual resolved font family: '{font_info.family()}'")
        logger.debug(f"[FONT DEBUG]   -> Actual style name: '{font_info.styleName()}'")
        logger.debug(f"[FONT DEBUG]   -> Actual point size: {font_info.pointSize()}")
        logger.debug(f"[FONT DEBUG]   -> Actual pixel size: {font_info.pixelSize()}")
        logger.debug(f"[FONT DEBUG]   -> Is it bold? {font_info.bold()}")

        margins = self.content_layout.contentsMargins()
        border_width = 1
        horizontal_padding = margins.left() + margins.right() + (border_width * 2)

        screen = QApplication.primaryScreen()
        self.max_content_width = (int(screen.geometry().width() * config.popup_max_width_percent / 100)) - horizontal_padding

        header_font = QFont(config.font_family)
        header_font.setPixelSize(config.font_size_header)
        header_metrics = QFontMetrics(header_font)
        self.header_chars_per_line = self._find_chars_for_width(header_metrics, "Header")

        def_font = QFont(config.font_family)
        def_font.setPixelSize(config.font_size_definitions)
        def_metrics = QFontMetrics(def_font)
        self.def_chars_per_line = self._find_chars_for_width(def_metrics, "Definition")

        logger.debug(f"[CALIBRATE] Max content width: {self.max_content_width}px")
        logger.debug(f"[CALIBRATE] Empirically found {self.header_chars_per_line} header chars/line")
        logger.debug(f"[CALIBRATE] Empirically found {self.def_chars_per_line} definition chars/line")
        self.is_calibrated = True

    def _find_chars_for_width(self, metrics: QFontMetrics, name: str) -> int:
        low = 1
        high = 500
        best_fit = 1

        while low <= high:
            mid = (low + high) // 2
            if mid == 0: break

            test_string = 'x' * mid
            current_width = metrics.horizontalAdvance(test_string)

            if current_width <= self.max_content_width:
                best_fit = mid
                low = mid + 1
            else:
                high = mid - 1

        return best_fit if best_fit > 0 else 50

    def set_latest_data(self, data, context=None):
        with self._data_lock:
            self._latest_data = data
            self._latest_context = context

    def get_latest_data(self):
        with self._data_lock:
            return self._latest_data

    def process_latest_data_loop(self):
        if not self.is_calibrated:
            self._calibrate_empirically()

        if self.locked:
            return  # frozen until unlocked; anything looked up meanwhile is dropped on unlock

        latest_data = self.get_latest_data()
        if latest_data and latest_data != self._last_latest_data:
            # update popup content
            with self._data_lock:
                self._context = self._latest_context
            self._calculate_content_and_size_char_count(latest_data)
        self._last_latest_data = latest_data

        if self._latest_data and self.input_loop.is_virtual_hotkey_down() and config.is_enabled:
            self.show_popup()
        else:
            self.hide_popup()

        mouse_pos = QCursor.pos()
        self.move_to(mouse_pos.x(), mouse_pos.y())

    @staticmethod
    def _display_len(text):
        # rough width in 'x' units: japanese characters are about twice as wide
        return sum(2 if ord(c) > 0x2E80 else 1 for c in text)

    @staticmethod
    def jl_deconjugation(entry: DictionaryEntry) -> str:
        """'撫でていた ～teiru→past', like JL; empty if the word wasn't conjugated."""
        steps = [p for p in reversed(entry.deconjugation_process or ()) if p and not p.startswith('(')]
        if not steps:
            return ''
        return f"{entry.matched_text} ～{'→'.join(steps)}".strip()

    def _render_jl_entry(self, entry: DictionaryEntry):
        """JL's popup layout: word, reading, deconjugation and frequency on one line, the dictionary name,
        then one line per sense with all glosses."""
        fs_def = config.font_size_definitions
        fs_small = max(8, round(fs_def * 0.9))
        header_html = f'<span style="color:{config.color_highlight_word}; font-size:{config.font_size_header}px;">{entry.written_form}</span>'
        header_calc = entry.written_form
        if entry.reading:
            header_html += f' <span style="color:{config.color_highlight_reading}; font-size:{round(config.font_size_header * 0.8)}px;">{entry.reading}</span>'
            header_calc += ' ' + entry.reading
        deconjugation = self.jl_deconjugation(entry)
        if deconjugation:
            header_html += f' <span style="color:{config.color_deconjugation}; font-size:{fs_small}px;">{html.escape(deconjugation)}</span>'
        frequency = freqlist.rank(entry)
        if frequency is not None:
            header_html += f' <span style="color:{config.color_frequency}; font-size:{fs_small}px;">#{frequency}</span>'
        header_html += MARK_PLACEHOLDER
        ratio = self._display_len(header_calc) / self.header_chars_per_line \
            + self._display_len(f" {deconjugation} #{frequency}") / self.def_chars_per_line

        dict_html = f'<br><span style="color:{config.color_dictionary}; font-size:{max(8, round(fs_def * 0.7))}px;">JMdict</span>'

        sense_lines = []
        numbered = len(entry.senses) > 1
        for idx, sense in enumerate(entry.senses):
            parts = [f"({idx + 1})"] if numbered else []
            if sense.get('pos'):
                parts.append(f"({', '.join(sense['pos'])})")
            if sense.get('tags'):
                parts.append(f"({', '.join(sense['tags'])})")
            parts.append('; '.join(sense.get('glosses', [])))
            line = ' '.join(parts)
            ratio = max(ratio, self._display_len(line) / self.def_chars_per_line)
            sense_lines.append(html.escape(line))
        definitions_html = f'<br><span style="color:{config.color_foreground}; font-size:{fs_def}px;">{"<br>".join(sense_lines)}</span>'
        return f"{header_html}{dict_html}{definitions_html}", ratio

    def _render_kanji_entry(self, entry: KanjiEntry, index: int):
        # Colors and sizes from config
        c_word = config.color_highlight_word
        c_read = config.color_highlight_reading
        c_text = config.color_foreground
        fs_head = config.font_size_header
        fs_def = config.font_size_definitions
        show_details = config.show_examples or config.show_components

        readings_str = ", ".join(entry.readings)
        readings_str = f"[{readings_str}]"

        header_html = f"""
                    <span style="font-size:{fs_head}px; color:{c_word}; padding-right: 8px;">{entry.character}</span>
                    <span style="font-size:{fs_head - 2}px; color:{c_read};"> {readings_str}</span>{MARK_PLACEHOLDER}
        """

        meanings_str = ", ".join(entry.meanings)
        meanings_html = f'<span style="font-size:{fs_def}px; color:{c_text};"> {meanings_str}</span>'
        if not config.compact_mode:
            meanings_html = f'<span style="font-size:{fs_def}px; color:{c_text};"> [字]</span><div>{meanings_html}</div>'

        examples_html = ""
        if config.show_examples:
            ex_parts = []
            for ex in entry.examples:
                part = (f"<span style='font-size:{fs_head - 2}px; color:{c_word}'>{ex['w']}</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_read}'>[{ex['r']}]</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_text}'>{ex['m']}</span>")
                ex_parts.append(part)
            if ex_parts:
                examples_html = f'<div>' \
                                f'{"; ".join(ex_parts)}</div>'

        components_html = ""
        if config.show_components:
            comp_parts = []
            for c in entry.components:
                part = (f"<span style='font-size:{fs_def}px; color:{c_word}'>{c.get('c', '')}</span> "
                        f"<span style='font-size:{fs_def}px; color:{c_text}'>{c.get('m', '')}</span>")
                comp_parts.append(part)
            if comp_parts:
                components_html = f'<div>{", ".join(comp_parts)}</div>'

        return f"""
        <div style="border: 1px solid {config.color_highlight_word};">
            {header_html}
            {meanings_html}
            {examples_html}
            {components_html}
        </div>
        """

    def _calculate_content_and_size_char_count(self, entries: Optional[List[DictionaryEntry]]):
        self._entries, self._entry_htmls, self._entry_heights, self._shown = [], [], [], None
        if not self.is_calibrated: return
        if not entries: return
        self._entries = list(entries)

        all_html_parts = []
        max_ratio = 0.0

        for i, entry in enumerate(entries):
            if isinstance(entry, KanjiEntry):
                header_definition = ', '.join(
                    entry.meanings) if config.show_examples or config.show_components else '[字]'
                header_text_calc = f"{entry.character} {', '.join(entry.readings)} {header_definition}"
                max_ratio = max(max_ratio, len(header_text_calc) / self.header_chars_per_line)

                max_ratio = max(max_ratio, 0.7)

                all_html_parts.append(self._render_kanji_entry(entry, i))
                continue

            if config.popup_layout == 'jl':
                entry_html, entry_ratio = self._render_jl_entry(entry)
                max_ratio = max(max_ratio, entry_ratio)
                all_html_parts.append(entry_html)
                continue

            header_text_calc = entry.written_form
            if entry.reading: header_text_calc += f" [{entry.reading}]"
            header_ratio = len(header_text_calc) / self.header_chars_per_line
            max_ratio = max(max_ratio, header_ratio)

            # --- HTML construction ---
            header_html = f'<span style="color: {config.color_highlight_word}; font-size:{config.font_size_header}px;">{entry.written_form}</span>'
            if entry.reading: header_html += f' <span style="color: {config.color_highlight_reading}; font-size:{config.font_size_header - 2}px;">[{entry.reading}]</span>'
            if entry.deconjugation_process and config.show_deconjugation:
                deconj_str = " ← ".join(p for p in entry.deconjugation_process if p)
                if deconj_str:
                    header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.8;">({deconj_str})</span>'
            frequency = freqlist.rank(entry)
            if config.show_frequency and frequency is not None:
                header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.6;">#{frequency}</span>'
            header_html += MARK_PLACEHOLDER
            def_text_parts_calc = []
            def_text_parts_html = []
            for idx, sense in enumerate(entry.senses):
                glosses = sense.get('glosses', [])
                glosses_str = ""
                if glosses:
                    glosses_str = ", ".join(glosses) if config.show_all_glosses else sense.get('glosses')[0]
                pos_list  = sense.get('pos', [])
                tags_list = sense.get('tags', [])
                sense_calc = f"({idx + 1})" if config.show_all_glosses else ""
                sense_html = f"<b>({idx + 1})</b> " if config.show_all_glosses else ""
                if config.show_pos and pos_list:
                    pos_str = f' ({", ".join(pos_list)})'
                    sense_calc += pos_str
                    sense_html += f'<span style="color:{config.color_foreground}; opacity:0.7;"><i>{pos_str}</i></span> '
                if config.show_tags and tags_list:
                    tags_str = f' [{", ".join(tags_list)}]'
                    sense_calc += tags_str
                    sense_html += f'<span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.7;">{tags_str}</span> '
                sense_calc += glosses_str
                sense_html += glosses_str
                def_text_parts_calc.append(sense_calc)
                def_text_parts_html.append(sense_html)

            if config.compact_mode:
                separator = "; "
                full_def_text_html = separator.join(def_text_parts_html)
                def_ratio = len(separator.join(def_text_parts_calc)) / self.def_chars_per_line
                max_ratio = max(max_ratio, def_ratio)
            else:
                separator = "<br>"
                full_def_text_html = separator.join(def_text_parts_html)
                for def_text_calc in def_text_parts_calc:
                    def_ratio = len(def_text_calc) / self.def_chars_per_line
                    max_ratio = max(max_ratio, def_ratio)

            definitions_html_final = f'{" " if config.compact_mode else "<br>"}<span style="font-size:{config.font_size_definitions}px;">{full_def_text_html}</span>'
            all_html_parts.append(f"{header_html}{definitions_html_final}")

        optimal_content_width = self.max_content_width * min(1.0, max_ratio)
        optimal_content_width = max(optimal_content_width, 200)

        self._entry_htmls = all_html_parts
        self._content_width = int(optimal_content_width)
        for n in range(1, len(all_html_parts) + 1):
            self.probe_label.setText(self._join_entries(n))
            self._entry_heights.append(self.probe_label.heightForWidth(self._content_width))

    def _padding(self):
        margins = self.content_layout.contentsMargins()
        border_width = 1
        return (margins.left() + margins.right() + (border_width * 2),
                margins.top() + margins.bottom() + (border_width * 2))

    def _join_entries(self, n):
        return '<hr style="margin-top: 0px; margin-bottom: 0px;">'.join(self._entry_htmls[:n])

    def _fit_to_height(self, max_height):
        """Show as many entries as fit within max_height (at least one, clipped if need be)."""
        if not self._entry_htmls:
            return
        horizontal_padding, vertical_padding = self._padding()
        max_content_height = max_height - vertical_padding

        count = 1
        for n, h in enumerate(self._entry_heights, start=1):
            if h <= max_content_height:
                count = n
        height = min(self._entry_heights[count - 1], max_content_height) + vertical_padding

        if self._shown == (count, height):
            return
        if self._shown is None or self._shown[0] != count:
            self.display_label.setText(self._join_entries(count))
        self.setFixedSize(QSize(self._content_width + horizontal_padding, height))
        self._shown = (count, height)

    def move_to(self, x, y):
        cursor_point = QPoint(x, y)
        screen = QApplication.screenAt(cursor_point) or QApplication.primaryScreen()
        screen_geo = screen.geometry()
        offset = 15

        ratio = screen.devicePixelRatio()
        x, y = magpie_manager.transform_raw_to_visual((int(x), int(y)), ratio)

        # --- Size limit ---
        mode = config.popup_position_mode
        max_height = screen_geo.height() if config.popup_max_height_percent <= 0 \
            else int(screen_geo.height() * config.popup_max_height_percent / 100)
        if mode == 'always_below':
            # shrink to the space under the cursor instead of ever moving above it;
            # only near the very bottom of the screen is it pushed up to stay readable
            min_height = 120
            space_below = screen_geo.bottom() - (y + offset)
            max_height = max(min(max_height, space_below), min_height)
        self._fit_to_height(max_height)
        popup_size = self.size()

        # --- Positioning logic based on mode ---
        if mode == 'always_below':
            # X: Flip, Y: always below the cursor
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset
            final_y = y + offset

        elif mode == 'visual_novel_mode':
            # --- Vertical Position (VN Mode) ---
            screen_height = screen_geo.height()
            cursor_y_in_screen = y - screen_geo.top()
            is_below = True
            if cursor_y_in_screen > (2 * screen_height / 3):  # Lower third
                is_below = False  # Place above
            elif cursor_y_in_screen < (screen_height / 3):  # Upper third
                is_below = True  # Place below
            else:  # Middle third
                is_below = cursor_y_in_screen < (screen_height / 2)
            final_y = (y + offset) if is_below else (y - popup_size.height() - offset)

            # Vertical Push
            if final_y < screen_geo.top(): final_y = screen_geo.top()
            if final_y + popup_size.height() > screen_geo.bottom():
                final_y = screen_geo.bottom() - popup_size.height()

            # --- Horizontal Position (VN Mode) ---
            screen_width = screen_geo.width()
            cursor_x_in_screen = x - screen_geo.left()
            # Define anchor points for interpolation
            pos_right = x + offset
            pos_center = x - popup_size.width() / 2.0
            pos_left = x - popup_size.width() - offset

            # Interpolate smoothly between right, center, and left alignment
            if cursor_x_in_screen < screen_width / 2.0:
                ratio = cursor_x_in_screen / (screen_width / 2.0)
                final_x = pos_right * (1 - ratio) + pos_center * ratio
            else:
                ratio = (cursor_x_in_screen - (screen_width / 2.0)) / (screen_width / 2.0)
                final_x = pos_center * (1 - ratio) + pos_left * ratio

        elif mode == 'flip_horizontally':
            # X: Flip, Y: Push
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            final_y = y + offset
            if final_y + popup_size.height() > screen_geo.bottom(): final_y = screen_geo.bottom() - popup_size.height()
            if final_y < screen_geo.top(): final_y = screen_geo.top()

        elif mode == 'flip_vertically':
            # X: Push, Y: Flip
            final_x = x + offset
            if final_x + popup_size.width() > screen_geo.right(): final_x = screen_geo.right() - popup_size.width()
            if final_x < screen_geo.left(): final_x = screen_geo.left()

            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        else:  # 'flip_both'
            # X: Flip
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            # Y: Flip
            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        # Final clamp to ensure the popup is always fully visible.
        # This acts as a safeguard against any edge cases.
        final_x = max(screen_geo.left(), min(final_x, screen_geo.right() - popup_size.width()))
        final_y = max(screen_geo.top(), min(final_y, screen_geo.bottom() - popup_size.height()))

        self.move(int(final_x), int(final_y))

    # --- mining mode ---
    def toggle_lock(self):
        if self.locked:
            self.unlock()
        elif self.is_visible and self._entry_htmls:
            self.lock()

    def lock(self):
        self.locked = True
        self.shared_state.popup_locked = True
        self._mined = {}
        logger.info("Popup locked for mining.")

        # show every entry, scrollable, keeping the popup where it is
        horizontal_padding, vertical_padding = self._padding()
        self.display_label.setText(self._join_entries(len(self._entry_htmls)))
        self.display_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._set_footer("Click an entry to add it to Anki  ·  Esc / middle click to close"
                         if config.anki_enabled else "Esc / middle click to close")
        footer_height = self.footer_label.heightForWidth(self._content_width) + self.content_layout.spacing()
        full_height = self._entry_heights[-1] + footer_height + vertical_padding

        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        screen_geo = screen.geometry()
        max_height = screen_geo.height() if config.popup_max_height_percent <= 0 \
            else int(screen_geo.height() * config.popup_max_height_percent / 100)
        max_height = min(max_height, screen_geo.bottom() - self.y())
        height = min(full_height, max(max_height, self.height()))

        needs_scroll = full_height > height
        self.scroll_area.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOn if needs_scroll else Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        width = self._content_width + horizontal_padding + (SCROLLBAR_WIDTH if needs_scroll else 0)
        # keep the right edge on screen if the scrollbar made it wider
        if self.x() + width > screen_geo.right():
            self.move(screen_geo.right() - width, self.y())
        self.setFixedSize(QSize(width, height))
        self.scroll_area.verticalScrollBar().setValue(0)
        self._shown = None
        if IS_WINDOWS:
            self.native_handle = int(self.winId())
        logger.info(f"Popup locked at {self.geometry()} (dpr {screen.devicePixelRatio()}), "
                    f"{len(self._entries)} entries, scrollable: {needs_scroll}")

    def unlock(self):
        if not self.locked:
            return
        self.locked = False
        logger.info("Popup unlocked.")
        self.footer_label.hide()
        self.display_label.unsetCursor()
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.verticalScrollBar().setValue(0)
        # drop whatever was looked up while locked; the next mouse move starts fresh
        with self._data_lock:
            self._latest_data = None
            self._latest_context = None
        self._last_latest_data = None
        self._entries, self._entry_htmls, self._entry_heights, self._shown = [], [], [], None
        self.hide_popup()
        self.shared_state.popup_locked = False

    def _on_click_while_locked(self):
        # clicks inside the popup are for mining/scrolling; anywhere else closes it
        if not self.geometry().contains(QCursor.pos()):
            logger.info("Popup: click outside, closing.")
            self.unlock()

    def _set_footer(self, text, color=None):
        self.footer_label.setText(
            f'<span style="color:{color or config.color_foreground}; font-size:{config.font_size_definitions - 2}px;">'
            f'{html.escape(text)}</span>')
        self.footer_label.show()

    def _on_mine_click(self):
        pos = self.display_label.mapFromGlobal(QCursor.pos())
        logger.info(f"Mining: click in popup at label y={pos.y()}")
        if self.display_label.rect().contains(pos):
            self._mine(self._entry_index_at(pos.y()))

    def _on_scroll(self, delta):
        scroll_bar = self.scroll_area.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.value() - int(delta / 120 * 60))

    def _entry_index_at(self, y):
        # _entry_heights[i] is where entry i ends, in label coordinates (scrolling included)
        return next((i for i, h in enumerate(self._entry_heights) if y <= h), len(self._entry_heights) - 1)

    def eventFilter(self, obj, event):
        # on windows clicks come through the input hook instead (_on_mine_click)
        if (not IS_WINDOWS and obj is self.display_label and self.locked and event.type() == QEvent.Type.MouseButtonRelease
                and event.button() == Qt.MouseButton.LeftButton):
            self._mine(self._entry_index_at(event.position().y()))
            return True
        return super().eventFilter(obj, event)

    def _mine(self, index):
        if not self.locked or not self._entries:
            return
        logger.info(f"Mining: clicked entry {index + 1}")
        if not config.anki_enabled:
            self._set_footer("Anki mining is turned off in Settings")
            return
        if index >= len(self._entries):
            return
        if self._mined.get(index) in ('pending', 'added'):
            if self._mined[index] == 'added':
                self._set_footer("Already added", MINED_COLORS['added'])
            else:
                self._set_footer("Adding to Anki…")
            return
        entry = self._entries[index]
        sentence = ankiconnect.extract_sentence(*self._context) if self._context else ''
        self._mined[index] = 'pending'
        self._set_footer("Adding to Anki…")
        threading.Thread(target=self._mine_worker, args=(index, entry, sentence), daemon=True,
                         name="AnkiMine").start()

    def _mine_worker(self, index, entry, sentence):
        word = getattr(entry, 'written_form', None) or getattr(entry, 'character', '')
        try:
            ankiconnect.add_note(entry, sentence)
            self._mine_finished.emit(index, 'added', f"Added {word} to {config.anki_deck}")
        except ankiconnect.DuplicateNoteError:
            self._mine_finished.emit(index, 'duplicate', f"{word} is already in Anki")
        except ankiconnect.AnkiError as e:
            logger.warning(f"Anki: could not add '{word}': {e}")
            self._mine_finished.emit(index, 'failed', f"Anki: {e}")
        except Exception as e:
            logger.exception("Anki: unexpected error while mining")
            self._mine_finished.emit(index, 'failed', f"Anki error: {e}")

    def _on_mine_finished(self, index, status, message):
        if not self.locked:
            return
        self._mined[index] = status
        mark = {'added': f'<span style="color:{MINED_COLORS["added"]};"> ✓</span>',
                'duplicate': f'<span style="color:{MINED_COLORS["duplicate"]};"> ✗ already in Anki</span>'}.get(status)
        if mark and index < len(self._entry_htmls):
            self._entry_htmls[index] = self._entry_htmls[index].replace(MARK_PLACEHOLDER, mark, 1)
            scroll = self.scroll_area.verticalScrollBar().value()
            self.display_label.setText(self._join_entries(len(self._entry_htmls)))
            self.scroll_area.verticalScrollBar().setValue(scroll)
        self._set_footer(message, MINED_COLORS.get(status))

    def hide_popup(self):
        # logger.debug(f"hide_popup triggered while visibility:{self.is_visible}")
        if not self.is_visible:
            return
        self.hide()
        self.is_visible = False
        QTimer.singleShot(50, lambda: self._release_lock_safely())  # prevent popup from being screenshotted
        self._restore_focus_on_mac()

    def _release_lock_safely(self):
        logger.debug("hide_popup releasing lock...")
        self.shared_state.screen_lock.release()
        logger.debug("...successfully released lock by hide_popup")

    def show_popup(self):
        # logger.debug(f"show_popup triggered while visibility:{self.is_visible}")
        if self.is_visible:
            return
        logger.debug("show_popup acquiring lock...")
        self.shared_state.screen_lock.acquire()
        logger.debug("...successfully acquired lock by show_popup")

        self._store_active_window_on_mac()
        self.show()
        if IS_MACOS:
            self.raise_()

        self.is_visible = True

    def reapply_settings(self):
        logger.debug("Popup: Re-applying settings and triggering font recalibration.")
        self.unlock()
        self._apply_frame_stylesheet()
        # By setting is_calibrated to False, the main loop will automatically
        # run _calibrate_empirically() again with the new font settings.
        self.is_calibrated = False
        self._last_latest_data = None  # re-layout the current lookup with the new size limits

    def _store_active_window_on_mac(self):
        """Store the currently active window for focus restoration (macOS only)."""
        if not IS_MACOS or not Quartz:
            return

        try:
            # Get the currently active application
            active_app = Quartz.NSWorkspace.sharedWorkspace().frontmostApplication()
            if active_app:
                # Store the application reference instead of trying to get the window
                # We'll use the application to restore focus later
                self._previous_active_window_on_mac = active_app
        except Exception as e:
            logger.warning(f"Failed to store active window: {e}")
            self._previous_active_window_on_mac = None

    def _restore_focus_on_mac(self):
        """Restore focus to the previously active application (macOS only)."""
        if not IS_MACOS or not Quartz or not self._previous_active_window_on_mac:
            return

        try:
            # Activate the previously active application
            self._previous_active_window_on_mac.activateWithOptions_(Quartz.NSApplicationActivateAllWindows)
        except Exception as e:
            logger.warning(f"Failed to restore focus: {e}")
        finally:
            # Clear the stored application reference
            self._previous_active_window_on_mac = None
