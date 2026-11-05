"""Tests for the Pactlyn theme system, brand styling, and theme switching."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from pactlyn.ui.theme import (
    COLOR_PINE,
    COLOR_TERRACOTTA,
    DARK_BG,
    LIGHT_BG,
    BrandWidget,
    get_saved_theme,
    get_stylesheet,
    save_theme,
    status_color,
)


def _ensure_qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def test_theme_stylesheets_contain_brand_colors() -> None:
    light_css = get_stylesheet("light")
    dark_css = get_stylesheet("dark")

    # Light theme contains brand forest green, warm terracotta, and sand cream
    assert COLOR_PINE in light_css
    assert COLOR_TERRACOTTA in light_css
    assert LIGHT_BG in light_css

    # Dark theme contains midnight obsidian pine and terracotta
    assert DARK_BG in dark_css
    assert COLOR_TERRACOTTA in dark_css


def test_status_color_helper() -> None:
    for mode in ("light", "dark"):
        for status_name in ("success", "warning", "error", "info", "muted"):
            col = status_color(status_name, mode=mode)  # type: ignore[arg-type]
            assert col.startswith("#")
            assert len(col) in (4, 7)


def test_theme_persistence() -> None:
    _ensure_qapp()
    save_theme("dark")
    assert get_saved_theme() == "dark"

    save_theme("light")
    assert get_saved_theme() == "light"


def test_brand_widget_rendering_and_mode_switching() -> None:
    _ensure_qapp()
    widget = BrandWidget(mode="light")
    assert "pact" in widget.title_label.text()
    assert "lyn" in widget.title_label.text()
    assert "YOUR COMMITMENTS, CARRIED THROUGH" in widget.tagline_label.text()

    # Switch to dark
    widget.set_mode("dark")
    assert "pact" in widget.title_label.text()
    assert "lyn" in widget.title_label.text()


def test_sidebar_state_persistence() -> None:
    _ensure_qapp()
    from pactlyn.ui.theme import get_saved_sidebar_state, save_sidebar_state

    save_sidebar_state(False)
    assert get_saved_sidebar_state() is False

    save_sidebar_state(True)
    assert get_saved_sidebar_state() is True


def test_create_sidebar_icon() -> None:
    _ensure_qapp()
    from pactlyn.ui.theme import create_sidebar_icon

    icon_light = create_sidebar_icon("#193A35", 18)
    assert not icon_light.isNull()

    icon_dark = create_sidebar_icon("#FFFFFF", 18)
    assert not icon_dark.isNull()
