"""Pactlyn theme and design system.

Implements the official Pactlyn brand identity:
- Deep forest green (pine) #193A35
- Warm terracotta (rust) #C66F50
- Warm sand/cream #F5F1E8
- Muted slate/sage #68756F

Provides both Light (warm cream + forest pine + terracotta) and Dark
(midnight obsidian pine + terracotta + warm cream typography) themes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

ThemeMode = Literal["light", "dark"]

# Color palette constants sampled from brand identity
COLOR_PINE = "#193A35"
COLOR_PINE_HOVER = "#234D46"
COLOR_PINE_DEEP = "#11211E"
COLOR_PINE_DARKEST = "#0C1614"

COLOR_TERRACOTTA = "#C66F50"
COLOR_TERRACOTTA_HOVER = "#D77B5C"
COLOR_TERRACOTTA_PRESSED = "#B05C3F"
COLOR_TERRACOTTA_LIGHT = "#F4DDD4"
COLOR_TERRACOTTA_TINT_DARK = "#3D241C"
_CHECK_ICON = Path(__file__).with_name("check.svg").as_posix()

# Light theme tokens
LIGHT_BG = "#F5F1E8"
LIGHT_SIDEBAR_BG = "#193A35"
LIGHT_CARD_BG = "#FFFFFF"
LIGHT_CARD_ALT = "#EFE9DC"
LIGHT_INPUT_BG = "#FFFFFF"
LIGHT_BORDER = "#E3DAC9"
LIGHT_BORDER_SUBTLE = "#ECE5D8"
LIGHT_TEXT_PRIMARY = "#193A35"
LIGHT_TEXT_MUTED = "#68756F"
LIGHT_TEXT_SUBDUED = "#939E98"

# Dark theme tokens
DARK_BG = "#111E1B"
DARK_SIDEBAR_BG = "#0C1614"
DARK_CARD_BG = "#172A26"
DARK_CARD_ALT = "#1E3530"
DARK_INPUT_BG = "#132421"
DARK_BORDER = "#26433C"
DARK_BORDER_SUBTLE = "#1E3630"
DARK_TEXT_PRIMARY = "#F5F1E8"
DARK_TEXT_MUTED = "#9DB0AA"
DARK_TEXT_SUBDUED = "#6E837D"

# Status colors
STATUS_COLORS = {
    "light": {
        "success": "#1E6B52",
        "warning": "#C66F50",
        "error": "#BA382E",
        "info": "#235B52",
        "muted": "#68756F",
        "badge_success_bg": "#E5F4EE",
        "badge_warning_bg": "#FDF0EB",
        "badge_error_bg": "#FCEBEA",
    },
    "dark": {
        "success": "#34D399",
        "warning": "#FBBF24",
        "error": "#F87171",
        "info": "#60A5FA",
        "muted": "#9DB0AA",
        "badge_success_bg": "#14372D",
        "badge_warning_bg": "#3D2817",
        "badge_error_bg": "#3E1C1A",
    },
}


def get_saved_theme() -> ThemeMode:
    settings = QSettings("Pactlyn", "Pactlyn")
    value = str(settings.value("ui/theme", "light")).lower()
    return "dark" if value == "dark" else "light"


def save_theme(mode: ThemeMode) -> None:
    settings = QSettings("Pactlyn", "Pactlyn")
    settings.setValue("ui/theme", mode)


def get_saved_sidebar_state() -> bool:
    settings = QSettings("Pactlyn", "Pactlyn")
    value = str(settings.value("ui/sidebar_visible", "true")).lower()
    return value == "true"


def save_sidebar_state(visible: bool) -> None:
    settings = QSettings("Pactlyn", "Pactlyn")
    settings.setValue("ui/sidebar_visible", "true" if visible else "false")


def create_sidebar_icon(color: str = "#FFFFFF", size: int = 18) -> QIcon:
    """Generate a clean SVG sidebar toggle icon rendered in the given color."""
    fill_rect = f'<path d="M4 4h4v16H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z" fill="{color}" opacity="0.3"/>'
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      {fill_rect}
      <rect x="3" y="3" width="18" height="18" rx="3" ry="3"/>
      <line x1="9" y1="3" x2="9" y2="21"/>
    </svg>'''
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def status_color(name: str, mode: ThemeMode = "light") -> str:
    palette = STATUS_COLORS.get(mode, STATUS_COLORS["light"])
    return palette.get(name, palette["muted"])


def get_stylesheet(mode: ThemeMode = "light") -> str:
    if mode == "dark":
        return f"""
/* Pactlyn Dark Theme — Midnight Obsidian Pine & Terracotta */

QMainWindow, QDialog {{
    background-color: {DARK_BG};
    color: {DARK_TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {DARK_TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
    font-size: 13px;
    selection-background-color: {COLOR_TERRACOTTA};
    selection-color: #ffffff;
}}

QWidget#central_widget, QStackedWidget {{
    background-color: {DARK_BG};
}}

QLabel {{
    background: transparent;
    background-color: transparent;
}}

/* Sidebar */
QFrame#sidebar {{
    background-color: {DARK_SIDEBAR_BG};
    border: none;
    border-right: 1px solid {DARK_BORDER_SUBTLE};
}}

QWidget#brand_widget, QWidget#brand_widget QLabel {{
    background: transparent;
    border: none;
}}

QPushButton#nav {{
    color: #C5D4CE;
    background-color: transparent;
    text-align: left;
    border: 0;
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton#nav:hover {{
    background-color: #172C27;
    color: #FFFFFF;
}}

QPushButton#nav:checked {{
    background-color: #213C36;
    color: #FFFFFF;
    font-weight: 600;
    border-left: 3px solid {COLOR_TERRACOTTA};
}}

QFrame#sidebar_divider {{
    color: rgba(255, 255, 255, 0.10);
    background-color: rgba(255, 255, 255, 0.10);
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* Brand & Typography */
QLabel#brand {{
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 700;
    padding: 8px 12px;
}}

QLabel#title {{
    color: {DARK_TEXT_PRIMARY};
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.4px;
}}

QLabel#muted {{
    color: {DARK_TEXT_MUTED};
    font-size: 13px;
}}

/* Cards & Containers */
QFrame#card, QFrame#metric_card {{
    background-color: {DARK_CARD_BG};
    border: 1px solid {DARK_BORDER};
    border-radius: 12px;
    padding: 14px;
}}

QFrame#card QLabel, QFrame#metric_card QLabel {{
    background: transparent;
    border: none;
}}

QFrame#metric_card:hover {{
    border-color: {COLOR_TERRACOTTA};
}}

/* Buttons */
QPushButton {{
    color: {DARK_TEXT_PRIMARY};
    background-color: {DARK_CARD_ALT};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: #26433C;
    border-color: #395E55;
    color: #FFFFFF;
}}

QPushButton:pressed {{
    background-color: #172B26;
}}

QPushButton:disabled {{
    background-color: #152421;
    color: #4D645E;
    border-color: #1D332D;
}}

QPushButton:default, QPushButton#primary {{
    color: #FFFFFF;
    background-color: {COLOR_TERRACOTTA};
    border: 1px solid {COLOR_TERRACOTTA};
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton:default:hover, QPushButton#primary:hover {{
    background-color: {COLOR_TERRACOTTA_HOVER};
    border-color: {COLOR_TERRACOTTA_HOVER};
    color: #FFFFFF;
}}

QPushButton:default:pressed, QPushButton#primary:pressed {{
    background-color: {COLOR_TERRACOTTA_PRESSED};
    border-color: {COLOR_TERRACOTTA_PRESSED};
}}

QPushButton:default:disabled, QPushButton#primary:disabled {{
    background-color: #384F49;
    border-color: #384F49;
    color: #7A908A;
}}

QPushButton#secondary {{
    color: {DARK_TEXT_PRIMARY};
    background-color: {DARK_CARD_ALT};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 8px 15px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton#secondary:hover {{
    background-color: #26433C;
    border-color: #395E55;
    color: #FFFFFF;
}}

QPushButton#secondary:pressed {{
    background-color: #172B26;
}}

QPushButton#secondary:disabled {{
    background-color: #152421;
    color: #4D645E;
    border-color: #1D332D;
}}

/* Sidebar Toggle Buttons */
QPushButton#sidebar_toggle_btn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px;
    min-width: 24px;
    min-height: 24px;
}}

QPushButton#sidebar_toggle_btn:hover {{
    background-color: #1A322C;
    border: 1px solid #2B574F;
}}

QPushButton#sidebar_toggle_btn:pressed {{
    background-color: #213C36;
}}

QWidget#top_bar QPushButton#sidebar_toggle_btn {{
    background-color: #172A26;
    border: 1px solid #26433C;
}}

QWidget#top_bar QPushButton#sidebar_toggle_btn:hover {{
    background-color: #1F3631;
    border: 1px solid {COLOR_TERRACOTTA};
}}

/* Inputs & Forms */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {DARK_INPUT_BG};
    color: {DARK_TEXT_PRIMARY};
    placeholder-text-color: #839790;
    border: 1.5px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1.5px solid {COLOR_TERRACOTTA};
    background-color: #162723;
}}

QLineEdit:read-only, QTextEdit:read-only {{
    background-color: #121F1C;
    color: {DARK_TEXT_PRIMARY};
    border-color: {DARK_BORDER_SUBTLE};
}}

QComboBox {{
    background-color: {DARK_INPUT_BG};
    color: {DARK_TEXT_PRIMARY};
    border: 1.5px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    min-height: 20px;
}}

QComboBox:focus {{
    border: 1.5px solid {COLOR_TERRACOTTA};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {DARK_CARD_BG};
    color: {DARK_TEXT_PRIMARY};
    border: 1px solid {DARK_BORDER};
    selection-background-color: {COLOR_TERRACOTTA};
    selection-color: #FFFFFF;
    padding: 4px;
    border-radius: 6px;
}}

QSpinBox {{
    background-color: {DARK_INPUT_BG};
    color: {DARK_TEXT_PRIMARY};
    border: 1.5px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
}}

/* Lists & Tables */
QListWidget {{
    background-color: {DARK_CARD_BG};
    border: 1px solid {DARK_BORDER};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}

QListWidget::item {{
    padding: 9px 12px;
    border-radius: 7px;
    margin: 2px 0px;
    color: {DARK_TEXT_PRIMARY};
}}

QListWidget::item:hover {{
    background-color: #1F3631;
}}

QListWidget::item:selected {{
    background-color: #26453E;
    color: #FFFFFF;
    border-left: 3px solid {COLOR_TERRACOTTA};
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {DARK_BORDER};
    border-radius: 10px;
    background-color: {DARK_CARD_BG};
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {DARK_TEXT_MUTED};
    padding: 10px 18px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    color: {COLOR_TERRACOTTA};
    font-weight: 600;
    border-bottom: 2px solid {COLOR_TERRACOTTA};
}}

QTabBar::tab:hover:!selected {{
    color: {DARK_TEXT_PRIMARY};
    background-color: #172A26;
    border-radius: 6px 6px 0 0;
}}

/* Checkboxes */
QCheckBox {{
    spacing: 8px;
    color: {DARK_TEXT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid {DARK_BORDER};
    background-color: {DARK_INPUT_BG};
}}

QCheckBox::indicator:checked {{
    image: url("{_CHECK_ICON}");
    background-color: {COLOR_TERRACOTTA};
    border-color: {COLOR_TERRACOTTA};
}}

/* Scrollbars */
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: #27433C;
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_TERRACOTTA};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
}}

QScrollBar:horizontal {{
    height: 8px;
    background: transparent;
}}

QScrollBar::handle:horizontal {{
    background-color: #27433C;
    border-radius: 4px;
    min-width: 24px;
}}

/* Group Boxes */
QGroupBox {{
    font-weight: 600;
    border: 1px solid {DARK_BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 18px;
    background-color: {DARK_CARD_BG};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: {DARK_TEXT_PRIMARY};
    background-color: {DARK_BG};
}}

/* Dialogs & Popups */
QDialog, QMessageBox, QInputDialog, QFileDialog {{
    background-color: {DARK_BG};
    color: {DARK_TEXT_PRIMARY};
}}

QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {{
    color: {DARK_TEXT_PRIMARY};
    background: transparent;
    font-size: 13px;
}}

QLabel#dialog_prompt {{
    font-size: 14px;
    font-weight: 600;
    color: {DARK_TEXT_PRIMARY};
    padding-bottom: 4px;
}}

QDialogButtonBox {{
    background: transparent;
    border: none;
}}

QDialogButtonBox QPushButton {{
    min-width: 82px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}

/* Tooltips & Menus */
QToolTip {{
    background-color: {DARK_CARD_ALT};
    color: {DARK_TEXT_PRIMARY};
    border: 1px solid {DARK_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

QMenu {{
    background-color: {DARK_CARD_BG};
    color: {DARK_TEXT_PRIMARY};
    border: 1px solid {DARK_BORDER};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 7px 18px;
    border-radius: 6px;
    color: {DARK_TEXT_PRIMARY};
}}

QMenu::item:selected {{
    background-color: {COLOR_TERRACOTTA};
    color: #FFFFFF;
}}

QMenu::separator {{
    height: 1px;
    background-color: {DARK_BORDER};
    margin: 4px 8px;
}}

QScrollArea {{
    border: none;
    background-color: {DARK_BG};
}}

QScrollArea > QWidget > QWidget {{
    background-color: {DARK_BG};
}}
"""

    # Light Theme
    return f"""
/* Pactlyn Light Theme — Warm Sand Cream, Deep Pine & Terracotta */

QMainWindow, QDialog {{
    background-color: {LIGHT_BG};
    color: {LIGHT_TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {LIGHT_TEXT_PRIMARY};
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", sans-serif;
    font-size: 13px;
    selection-background-color: {COLOR_TERRACOTTA};
    selection-color: #ffffff;
}}

QWidget#central_widget, QStackedWidget {{
    background-color: {LIGHT_BG};
}}

QLabel {{
    background: transparent;
    background-color: transparent;
}}

/* Sidebar */
QFrame#sidebar {{
    background-color: {LIGHT_SIDEBAR_BG};
    border: none;
}}

QWidget#brand_widget, QWidget#brand_widget QLabel {{
    background: transparent;
    border: none;
}}

QPushButton#nav {{
    color: #DDE7E4;
    background-color: transparent;
    text-align: left;
    border: 0;
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 500;
}}

QPushButton#nav:hover {{
    background-color: {COLOR_PINE_HOVER};
    color: #FFFFFF;
}}

QPushButton#nav:checked {{
    background-color: #29574F;
    color: #FFFFFF;
    font-weight: 600;
    border-left: 3px solid {COLOR_TERRACOTTA};
}}

QFrame#sidebar_divider {{
    color: rgba(255, 255, 255, 0.10);
    background-color: rgba(255, 255, 255, 0.10);
    border: none;
    max-height: 1px;
    min-height: 1px;
}}

/* Brand & Typography */
QLabel#brand {{
    color: #FFFFFF;
    font-size: 22px;
    font-weight: 700;
    padding: 8px 12px;
}}

QLabel#title {{
    color: {COLOR_PINE};
    font-size: 24px;
    font-weight: 700;
    letter-spacing: -0.4px;
}}

QLabel#muted {{
    color: {LIGHT_TEXT_MUTED};
    font-size: 13px;
}}

/* Cards & Containers */
QFrame#card, QFrame#metric_card {{
    background-color: {LIGHT_CARD_BG};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 12px;
    padding: 14px;
}}

QFrame#card QLabel, QFrame#metric_card QLabel {{
    background: transparent;
    border: none;
}}

QFrame#metric_card:hover {{
    border-color: {COLOR_TERRACOTTA};
}}

/* Buttons */
QPushButton {{
    color: {COLOR_PINE};
    background-color: {LIGHT_CARD_ALT};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    font-weight: 600;
    font-size: 13px;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: #E6DECE;
    border-color: #D3C7B2;
    color: {COLOR_PINE};
}}

QPushButton:pressed {{
    background-color: #DDD4C3;
}}

QPushButton:disabled {{
    background-color: #ECE7DD;
    color: #A3A29B;
    border-color: #E2DDD3;
}}

QPushButton:default, QPushButton#primary {{
    color: #FFFFFF;
    background-color: {COLOR_TERRACOTTA};
    border: 1px solid {COLOR_TERRACOTTA};
    border-radius: 8px;
    padding: 8px 18px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton:default:hover, QPushButton#primary:hover {{
    background-color: {COLOR_TERRACOTTA_HOVER};
    border-color: {COLOR_TERRACOTTA_HOVER};
    color: #FFFFFF;
}}

QPushButton:default:pressed, QPushButton#primary:pressed {{
    background-color: {COLOR_TERRACOTTA_PRESSED};
    border-color: {COLOR_TERRACOTTA_PRESSED};
}}

QPushButton:default:disabled, QPushButton#primary:disabled {{
    background-color: #C8BFAF;
    border-color: #C8BFAF;
    color: #FFFFFF;
}}

QPushButton#secondary {{
    color: {COLOR_PINE};
    background-color: {LIGHT_CARD_ALT};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 8px 15px;
    font-weight: 600;
    font-size: 13px;
}}

QPushButton#secondary:hover {{
    background-color: #E6DECE;
    border-color: #D3C7B2;
}}

QPushButton#secondary:pressed {{
    background-color: #DDD4C3;
}}

QPushButton#secondary:disabled {{
    background-color: #ECE7DD;
    color: #A3A29B;
    border-color: #E2DDD3;
}}

/* Sidebar Toggle Buttons */
QPushButton#sidebar_toggle_btn {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 6px;
    padding: 3px;
    min-width: 24px;
    min-height: 24px;
}}

QFrame#sidebar QPushButton#sidebar_toggle_btn {{
    background-color: transparent;
    border: 1px solid transparent;
}}

QFrame#sidebar QPushButton#sidebar_toggle_btn:hover {{
    background-color: #234D46;
    border: 1px solid #2B574F;
}}

QFrame#sidebar QPushButton#sidebar_toggle_btn:pressed {{
    background-color: #29574F;
}}

QWidget#top_bar QPushButton#sidebar_toggle_btn {{
    background-color: #EFE9DC;
    border: 1px solid #E3DAC9;
}}

QWidget#top_bar QPushButton#sidebar_toggle_btn:hover {{
    background-color: #E6DECE;
    border: 1px solid {COLOR_TERRACOTTA};
}}

QWidget#top_bar QPushButton#sidebar_toggle_btn:pressed {{
    background-color: #DDD4C3;
}}

/* Inputs & Forms */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {LIGHT_INPUT_BG};
    color: {LIGHT_TEXT_PRIMARY};
    placeholder-text-color: #7E8C85;
    border: 1.5px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 8px 12px;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border: 1.5px solid {COLOR_TERRACOTTA};
    background-color: #FFFFFF;
}}

QLineEdit:read-only, QTextEdit:read-only {{
    background-color: #FAF8F2;
    color: {LIGHT_TEXT_PRIMARY};
    border-color: {LIGHT_BORDER};
}}

QComboBox {{
    background-color: {LIGHT_INPUT_BG};
    color: {LIGHT_TEXT_PRIMARY};
    border: 1.5px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 7px 12px;
    min-height: 20px;
}}

QComboBox:focus {{
    border: 1.5px solid {COLOR_TERRACOTTA};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {LIGHT_CARD_BG};
    color: {LIGHT_TEXT_PRIMARY};
    border: 1px solid {LIGHT_BORDER};
    selection-background-color: {COLOR_TERRACOTTA};
    selection-color: #FFFFFF;
    padding: 4px;
    border-radius: 6px;
}}

QSpinBox {{
    background-color: {LIGHT_INPUT_BG};
    color: {LIGHT_TEXT_PRIMARY};
    border: 1.5px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 6px 10px;
}}

/* Lists & Tables */
QListWidget {{
    background-color: {LIGHT_CARD_BG};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 10px;
    padding: 6px;
    outline: none;
}}

QListWidget::item {{
    padding: 9px 12px;
    border-radius: 7px;
    margin: 2px 0px;
    color: {LIGHT_TEXT_PRIMARY};
}}

QListWidget::item:hover {{
    background-color: #F8F5EE;
}}

QListWidget::item:selected {{
    background-color: #EFE4D6;
    color: {COLOR_PINE};
    font-weight: 500;
    border-left: 3px solid {COLOR_TERRACOTTA};
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid {LIGHT_BORDER};
    border-radius: 10px;
    background-color: {LIGHT_CARD_BG};
    top: -1px;
}}

QTabBar::tab {{
    background-color: transparent;
    color: {LIGHT_TEXT_MUTED};
    padding: 10px 18px;
    font-weight: 500;
    border-bottom: 2px solid transparent;
    margin-right: 4px;
}}

QTabBar::tab:selected {{
    color: {COLOR_TERRACOTTA};
    font-weight: 600;
    border-bottom: 2px solid {COLOR_TERRACOTTA};
}}

QTabBar::tab:hover:!selected {{
    color: {LIGHT_TEXT_PRIMARY};
    background-color: #FAF7F0;
    border-radius: 6px 6px 0 0;
}}

/* Checkboxes */
QCheckBox {{
    spacing: 8px;
    color: {LIGHT_TEXT_PRIMARY};
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1.5px solid {LIGHT_BORDER};
    background-color: {LIGHT_INPUT_BG};
}}

QCheckBox::indicator:checked {{
    image: url("{_CHECK_ICON}");
    background-color: {COLOR_TERRACOTTA};
    border-color: {COLOR_TERRACOTTA};
}}

/* Scrollbars */
QScrollBar:vertical {{
    width: 8px;
    background: transparent;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background-color: #D6CCBC;
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {COLOR_TERRACOTTA};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
    height: 0px;
}}

QScrollBar:horizontal {{
    height: 8px;
    background: transparent;
}}

QScrollBar::handle:horizontal {{
    background-color: #D6CCBC;
    border-radius: 4px;
    min-width: 24px;
}}

/* Group Boxes */
QGroupBox {{
    font-weight: 600;
    border: 1px solid {LIGHT_BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding-top: 18px;
    background-color: {LIGHT_CARD_BG};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: {COLOR_PINE};
    background-color: {LIGHT_BG};
}}

/* Dialogs & Popups */
QDialog, QMessageBox, QInputDialog, QFileDialog {{
    background-color: {LIGHT_BG};
    color: {LIGHT_TEXT_PRIMARY};
}}

QDialog QLabel, QMessageBox QLabel, QInputDialog QLabel {{
    color: {LIGHT_TEXT_PRIMARY};
    background: transparent;
    font-size: 13px;
}}

QLabel#dialog_prompt {{
    font-size: 14px;
    font-weight: 600;
    color: {COLOR_PINE};
    padding-bottom: 4px;
}}

QDialogButtonBox {{
    background: transparent;
    border: none;
}}

QDialogButtonBox QPushButton {{
    min-width: 82px;
    padding: 8px 18px;
    font-size: 13px;
    font-weight: 600;
}}

/* Tooltips & Menus */
QToolTip {{
    background-color: #FFFFFF;
    color: {COLOR_PINE};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 12px;
}}

QMenu {{
    background-color: {LIGHT_CARD_BG};
    color: {LIGHT_TEXT_PRIMARY};
    border: 1px solid {LIGHT_BORDER};
    border-radius: 8px;
    padding: 4px;
}}

QMenu::item {{
    padding: 7px 18px;
    border-radius: 6px;
    color: {LIGHT_TEXT_PRIMARY};
}}

QMenu::item:selected {{
    background-color: {COLOR_TERRACOTTA};
    color: #FFFFFF;
}}

QMenu::separator {{
    height: 1px;
    background-color: {LIGHT_BORDER};
    margin: 4px 8px;
}}

QScrollArea {{
    border: none;
    background-color: {LIGHT_BG};
}}

QScrollArea > QWidget > QWidget {{
    background-color: {LIGHT_BG};
}}
"""


class BrandWidget(QWidget):
    """Header widget that displays the official Pactlyn logo mark and typography.

    Renders:
    - The interlocking knot icon badge
    - "pact" (forest green / cream) + "lyn" (terracotta)
    - Subtitle: "YOUR COMMITMENTS, CARRIED THROUGH"
    - Terracotta accent line
    """

    def __init__(self, mode: ThemeMode = "light", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("brand_widget")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._mode = mode
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(2, 2, 2, 4)
        main_layout.setSpacing(3)

        # Top row: Icon + wordmark
        top_row = QHBoxLayout()
        top_row.setSpacing(8)
        top_row.setContentsMargins(0, 0, 0, 0)

        # Icon
        self.icon_label = QLabel()
        self.icon_label.setObjectName("brand_icon")
        self.icon_label.setStyleSheet("background: transparent; border: none;")
        self.icon_label.setFixedSize(30, 30)
        svg_path = Path(__file__).with_name("pactlyn.svg")
        if svg_path.exists():
            pixmap = QIcon(str(svg_path)).pixmap(30, 30)
            self.icon_label.setPixmap(pixmap)
            self.icon_label.setScaledContents(True)
        top_row.addWidget(self.icon_label)

        # Wordmark
        self.title_label = QLabel()
        self.title_label.setObjectName("brand_title")
        self.title_label.setStyleSheet("background: transparent; border: none;")
        top_row.addWidget(self.title_label, 1)
        main_layout.addLayout(top_row)

        # Subtitle
        self.tagline_label = QLabel()
        self.tagline_label.setObjectName("brand_tagline")
        self.tagline_label.setStyleSheet("background: transparent; border: none;")
        self.tagline_label.setWordWrap(False)
        main_layout.addWidget(self.tagline_label)

        # Terracotta accent underline
        self.accent_line = QFrame()
        self.accent_line.setFixedHeight(2)
        self.accent_line.setFixedWidth(44)
        self.accent_line.setStyleSheet(
            f"background-color: {COLOR_TERRACOTTA}; border-radius: 1px;"
        )
        main_layout.addWidget(self.accent_line)

        self.set_mode(self._mode)

    def set_mode(self, mode: ThemeMode) -> None:
        self._mode = mode
        # In sidebar: if light mode, sidebar is deep forest green, so pact text is warm cream
        pact_color = "#FFFFFF"
        tagline_color = "#9DB0AA" if mode == "dark" else "#B3C4BF"

        self.title_label.setText(
            f'<div style="line-height: 1.0;">'
            f'<span style="font-size: 18px; font-weight: 800; color: {pact_color}; letter-spacing: -0.5px;">pact</span>'
            f'<span style="font-size: 18px; font-weight: 800; color: {COLOR_TERRACOTTA}; letter-spacing: -0.5px;">lyn</span>'
            f'</div>'
        )

        self.tagline_label.setText(
            f'<span style="font-size: 7px; font-weight: 700; color: {tagline_color}; '
            f'letter-spacing: 0.8px; text-transform: uppercase;">'
            f'YOUR COMMITMENTS, CARRIED THROUGH'
            f'</span>'
        )
