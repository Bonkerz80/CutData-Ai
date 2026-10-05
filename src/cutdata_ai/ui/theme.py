"""Application-wide Light and Dark themes for the branded Qt interface."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from ..config.settings import APPEARANCE_DARK, APPEARANCE_LIGHT, normalise_appearance


THEMES = {
    APPEARANCE_LIGHT: {
        "window": "#f3f5f7",
        "surface": "#ffffff",
        "surface_alt": "#fbfcfd",
        "input": "#ffffff",
        "text": "#17212b",
        "muted": "#66727d",
        "label": "#51606b",
        "title": "#26323a",
        "border": "#d5dbe1",
        "border_soft": "#d7dde1",
        "border_strong": "#c8d0d5",
        "alternate": "#f3f5f7",
        "selection": "#fbe3e3",
        "selection_text": "#17212b",
        "scrollbar": "#c3ccd3",
        "scrollbar_handle": "#8c9aa4",
        "note": "#fbfcfd",
        "tooltip": "#ffffff",
        "tooltip_text": "#17212b",
        "disabled": "#87929c",
        "success_bg": "#d9f1e4",
        "success_text": "#17643a",
        "warning_bg": "#fff0bd",
        "warning_text": "#765b00",
        "error_bg": "#fde0d8",
        "error_text": "#8a2d1d",
        "info_bg": "#e1f0f5",
        "info_text": "#205a6e",
        "button": "#eef1f4",
        "button_text": "#17212b",
        "dark_button": "#2f3a43",
        "dark_button_hover": "#1b2228",
        "dark_button_text": "#ffffff",
        "brand_dark": "#1b2228",
        "brand_border": "#313b43",
        "brand_muted": "#cbd2d7",
        "brand_pink": "#f4b2b2",
        "brand_red": "#CE1D1D",
        "brand_red_dark": "#a91616",
        "badge_border": "#e2b94e",
        "success_border": "#8bc6a2",
    },
    APPEARANCE_DARK: {
        "window": "#1b2024",
        "surface": "#252c32",
        "surface_alt": "#20272c",
        "input": "#2a333a",
        "text": "#f2f5f7",
        "muted": "#b8c2c9",
        "label": "#c9d2d8",
        "title": "#f2f5f7",
        "border": "#46515e",
        "border_soft": "#3e4953",
        "border_strong": "#596875",
        "alternate": "#252c32",
        "selection": "#5b2528",
        "selection_text": "#ffffff",
        "scrollbar": "#303a42",
        "scrollbar_handle": "#667783",
        "note": "#20272c",
        "tooltip": "#2b3339",
        "tooltip_text": "#f2f5f7",
        "disabled": "#7e8991",
        "success_bg": "#193d2b",
        "success_text": "#9fe0b6",
        "warning_bg": "#4b3b10",
        "warning_text": "#ffe18a",
        "error_bg": "#4a2525",
        "error_text": "#ffb5a6",
        "info_bg": "#1e3b46",
        "info_text": "#a8dce8",
        "button": "#303a42",
        "button_text": "#f2f5f7",
        "dark_button": "#36424b",
        "dark_button_hover": "#13181c",
        "dark_button_text": "#ffffff",
        "brand_dark": "#13181c",
        "brand_border": "#3a444d",
        "brand_muted": "#cbd2d7",
        "brand_pink": "#ffb7b7",
        "brand_red": "#CE1D1D",
        "brand_red_dark": "#a91616",
        "badge_border": "#9b7d20",
        "success_border": "#4e9a6b",
    },
}


def _set_palette(app: QApplication, colors: dict[str, str]) -> None:
    palette = QPalette()
    for role, key in (
        (QPalette.Window, "window"),
        (QPalette.WindowText, "text"),
        (QPalette.Base, "input"),
        (QPalette.AlternateBase, "alternate"),
        (QPalette.Text, "text"),
        (QPalette.Button, "button"),
        (QPalette.ButtonText, "button_text"),
        (QPalette.ToolTipBase, "tooltip"),
        (QPalette.ToolTipText, "tooltip_text"),
        (QPalette.PlaceholderText, "muted"),
        (QPalette.Highlight, "selection"),
        (QPalette.HighlightedText, "selection_text"),
        (QPalette.Link, "brand_red"),
    ):
        palette.setColor(role, QColor(colors[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText, QPalette.PlaceholderText):
        palette.setColor(QPalette.Disabled, role, QColor(colors["disabled"]))
    app.setPalette(palette)


def _stylesheet(colors: dict[str, str]) -> str:
    return f"""
        QWidget {{ color: {colors['text']}; font-family: 'Segoe UI'; font-size: 10pt; }}
        QMainWindow, QDialog {{ background: {colors['window']}; }}
        QFrame#brandHeader {{ background: {colors['brand_dark']}; border: 1px solid {colors['brand_border']}; border-radius: 7px; }}
        QFrame#brandRule {{ background: {colors['brand_red']}; border: none; }}
        QFrame#pptBrandBlock {{ background: {colors['brand_red']}; border-radius: 5px; }}
        QFrame#pptLogoSurface, QFrame#dialogLogoSurface {{ background: #ffffff; border-radius: 3px; }}
        QLabel#pptCompanyName {{ color: #ffffff; font-size: 8pt; font-weight: 700; letter-spacing: 0.5px; }}
        QLabel#headerProduct {{ color: #ffffff; font-size: 21pt; font-weight: 700; }}
        QLabel#headerTagline {{ color: {colors['brand_muted']}; font-size: 9pt; font-weight: 500; }}
        QFrame#dialogBrandHeader {{ background: {colors['brand_dark']}; border: 1px solid {colors['brand_border']}; border-radius: 6px; }}
        QLabel#dialogPublisher {{ color: {colors['brand_pink']}; font-size: 8pt; font-weight: 800; letter-spacing: 2px; }}
        QLabel#dialogTitle {{ color: #ffffff; font-size: 18pt; font-weight: 700; }}
        QLabel#dialogSubtitle {{ color: {colors['brand_muted']}; font-size: 9pt; }}
        QFrame#dialogIdentityCard {{ background: {colors['surface']}; border: 1px solid {colors['border_soft']}; border-left: 4px solid {colors['brand_red']}; border-radius: 5px; }}
        QLabel#dialogIdentityPublisher {{ color: {colors['brand_red']}; font-size: 8pt; font-weight: 800; letter-spacing: 2px; }}
        QLabel#dialogIdentityProduct {{ color: {colors['text']}; font-size: 16pt; font-weight: 700; }}
        QLabel#dialogIdentityVersion {{ color: {colors['muted']}; font-size: 9pt; font-weight: 600; }}
        QGroupBox {{ background: {colors['surface']}; border: 1px solid {colors['border']}; border-left: 3px solid {colors['brand_red']}; border-radius: 5px; margin-top: 9px; padding-top: 9px; }}
        QGroupBox#setupGroup, QGroupBox#dialogPrimaryGroup, QGroupBox#primaryGroup {{ border-left: 4px solid {colors['brand_red']}; }}
        QGroupBox#primaryGroup {{ background: {colors['surface_alt']}; }}
        QGroupBox#secondaryGroup, QGroupBox#dialogSecondaryGroup {{ border-left: 2px solid {colors['border_strong']}; }}
        QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {colors['title']}; font-weight: 700; }}
        QLabel#hint {{ color: {colors['muted']}; }}
        QLabel#formHeading {{ color: {colors['brand_red']}; font-size: 9pt; font-weight: 800; letter-spacing: 1px; padding-top: 5px; }}
        QLabel#statusBadge, QLabel#readyBadge, QLabel#mockBadge, QLabel#warningBadge, QLabel#errorBadge {{ padding: 7px 12px; border-radius: 14px; font-weight: 700; }}
        QLabel#readyBadge {{ background: {colors['success_bg']}; color: {colors['success_text']}; }}
        QLabel#mockBadge, QLabel#apiStatusNotice {{ background: {colors['warning_bg']}; color: {colors['warning_text']}; }}
        QLabel#warningBadge {{ background: {colors['error_bg']}; color: {colors['error_text']}; }}
        QLabel#errorBadge {{ background: #b3261e; color: #ffffff; }}
        QLabel#apiStatusNotice {{ padding: 8px 12px; border-radius: 5px; font-weight: 600; }}
        QPushButton#modeSwitch, QPushButton#appearanceSwitch {{ background: {colors['warning_bg']}; color: {colors['warning_text']}; border: 1px solid {colors['badge_border']}; border-radius: 6px; font-weight: 700; }}
        QPushButton#modeSwitch:checked, QPushButton#appearanceSwitch:checked {{ background: {colors['warning_bg']}; color: {colors['warning_text']}; }}
        QPushButton#modeSwitch:!checked, QPushButton#appearanceSwitch:!checked {{ background: {colors['success_bg']}; color: {colors['success_text']}; border-color: {colors['success_border']}; }}
        QPushButton#modeSwitch:hover, QPushButton#appearanceSwitch:hover {{ border: 2px solid {colors['brand_red']}; }}
        QPushButton#headerButton {{ background: #2a333a; color: #ffffff; border: 1px solid #56616a; border-radius: 5px; font-weight: 700; padding: 4px 11px; }}
        QPushButton#headerButton:hover {{ background: #3a464f; border-color: #ffffff; }}
        QPushButton#secondaryAction {{ background: {colors['dark_button']}; color: {colors['dark_button_text']}; font-weight: 700; }}
        QPushButton#secondaryAction:hover {{ background: {colors['dark_button_hover']}; border-color: {colors['brand_red']}; }}
        QLabel#statusLabel, QLabel#statusValue {{ color: {colors['text']}; }}
        QLabel#statusValue {{ font-weight: 600; }}
        QLabel#connectionSuccess {{ color: {colors['success_text']}; font-weight: 700; }}
        QLabel#connectionWarning {{ color: {colors['error_text']}; font-weight: 700; }}
        QLabel#resultStatus {{ color: {colors['muted']}; font-size: 11pt; }}
        QLabel#resultBanner {{ background: {colors['info_bg']}; color: {colors['info_text']}; padding: 8px 12px; border-radius: 5px; font-weight: 600; }}
        QPushButton#sectionToggle {{ text-align: left; font-weight: 700; }}
        QLabel#reviewBanner, QLabel#keyWarnings {{ background: {colors['warning_bg']}; color: {colors['warning_text']}; padding: 8px 12px; border-radius: 5px; font-weight: 700; }}
        QLabel#errorBanner {{ background: {colors['error_bg']}; color: {colors['error_text']}; padding: 8px 12px; border-radius: 5px; font-weight: 600; }}
        QFrame#inputPanel, QFrame#resultPanel {{ background: {colors['surface']}; border: 1px solid {colors['border_soft']}; border-radius: 7px; }}
        QScrollArea#resultScroll, QScrollArea#settingsScroll, QWidget#resultContent, QWidget#settingsContent {{ background: transparent; border: none; }}
        QFrame#valueCard {{ background: {colors['surface']}; border: 1px solid {colors['border_soft']}; border-left: 4px solid {colors['brand_red']}; border-radius: 5px; }}
        QLabel#valueLabel {{ color: {colors['label']}; font-size: 9pt; font-weight: 700; letter-spacing: 1px; }}
        QLabel#resultValue {{ color: {colors['text']}; font-size: 18pt; font-weight: 800; }}
        QLabel#resultValue[stateText="true"] {{ font-size: 13pt; }}
        QLabel#infoValue {{ color: {colors['text']}; font-weight: 600; }}
        QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{ min-height: 30px; background: {colors['input']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 3px; padding: 2px 6px; selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']}; }}
        QPlainTextEdit {{ background: {colors['note']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 3px; selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']}; }}
        QComboBox QAbstractItemView {{ background: {colors['input']}; color: {colors['text']}; border: 1px solid {colors['border']}; selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']}; }}
        QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus, QPlainTextEdit:focus {{ border: 1px solid {colors['brand_red']}; }}
        QPushButton {{ min-height: 30px; padding: 3px 12px; background: {colors['button']}; color: {colors['button_text']}; border: 1px solid {colors['border']}; border-radius: 3px; }}
        QPushButton:hover {{ border-color: {colors['brand_red']}; }}
        QPushButton#calculateButton {{ background: {colors['brand_red']}; color: white; border: 1px solid {colors['brand_red_dark']}; font-weight: 800; font-size: 12pt; border-radius: 5px; }}
        QPushButton#calculateButton:hover {{ background: {colors['brand_red_dark']}; }}
        QListWidget, QTableWidget {{ background: {colors['input']}; color: {colors['text']}; border: 1px solid {colors['border']}; border-radius: 5px; alternate-background-color: {colors['alternate']}; selection-background-color: {colors['selection']}; selection-color: {colors['selection_text']}; }}
        QListWidget::item {{ padding: 4px 8px; border-bottom: 1px solid {colors['border_soft']}; }}
        QListWidget::item:selected {{ background: {colors['selection']}; color: {colors['selection_text']}; border-left: 3px solid {colors['brand_red']}; }}
        QHeaderView::section {{ background: {colors['surface_alt']}; color: {colors['text']}; border: 1px solid {colors['border']}; padding: 4px; font-weight: 700; }}
        QTabBar::tab {{ color: {colors['muted']}; padding: 5px 9px; }}
        QTabBar::tab:selected {{ color: {colors['brand_red']}; border-bottom: 2px solid {colors['brand_red']}; }}
        QSplitter::handle {{ background: {colors['border']}; }}
        QScrollBar:vertical, QScrollBar:horizontal {{ background: {colors['scrollbar']}; border: none; margin: 0; }}
        QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{ background: {colors['scrollbar_handle']}; border-radius: 4px; min-height: 24px; min-width: 24px; }}
        QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; border: none; }}
        QToolTip {{ background: {colors['tooltip']}; color: {colors['tooltip_text']}; border: 1px solid {colors['border_strong']}; padding: 4px; }}
        QMenu {{ background: {colors['surface']}; color: {colors['text']}; border: 1px solid {colors['border']}; }}
        QMenu::item:selected {{ background: {colors['selection']}; color: {colors['selection_text']}; }}
        QCheckBox {{ color: {colors['text']}; spacing: 6px; }}
        QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {colors['border_strong']}; background: {colors['input']}; border-radius: 2px; }}
        QCheckBox::indicator:checked {{ background: {colors['brand_red']}; border-color: {colors['brand_red']}; }}
    """


def apply_theme(app: QApplication | None, appearance: str = APPEARANCE_LIGHT) -> str:
    """Apply a complete theme and return the normalized appearance name."""

    if app is None:
        return normalise_appearance(appearance)
    mode = normalise_appearance(appearance)
    colors = THEMES[mode]
    app.setStyle("Fusion")
    _set_palette(app, colors)
    app.setStyleSheet(_stylesheet(colors))
    app.setProperty("cutdataAppearance", mode)
    return mode

