"""Centralized theme tokens for the DiskForge UI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemeColors:
    """Color palette tokens."""

    window_bg: str
    text_primary: str
    brand_primary: str
    brand_primary_dark: str
    brand_primary_soft: str
    brand_accent: str
    brand_danger: str
    surface: str
    surface_alt: str
    surface_muted: str
    border: str
    border_soft: str
    text_inverted: str
    text_muted: str


@dataclass(frozen=True)
class ThemeTypography:
    """Typography tokens."""

    title_size_px: int
    subtitle_size_px: int
    title_weight: int
    subtitle_weight: int
    badge_weight: int
    section_weight: int


@dataclass(frozen=True)
class ThemeSpacing:
    """Spacing tokens used in QSS."""

    menubar_padding_px: int
    toolbar_spacing_px: int
    badge_padding: str
    button_padding: str
    sidebar_title_padding: str


@dataclass(frozen=True)
class ThemeRadii:
    """Border radius tokens."""

    group_box_px: int
    button_px: int
    badge_px: int


@dataclass(frozen=True)
class AomeiTheme:
    """AOMEI-inspired theme tokens."""

    colors: ThemeColors
    typography: ThemeTypography
    spacing: ThemeSpacing
    radii: ThemeRadii

    def qss(self) -> str:
        """Build the QSS stylesheet for the theme."""
        return f"""
        QMainWindow {{
            background-color: {self.colors.window_bg};
            color: {self.colors.text_primary};
        }}
        QMenuBar {{
            background-color: {self.colors.brand_primary};
            color: {self.colors.text_inverted};
            padding: {self.spacing.menubar_padding_px}px;
        }}
        QMenuBar::item:selected {{
            background-color: {self.colors.brand_primary_dark};
        }}
        QMenu {{
            background-color: {self.colors.surface};
            border: 1px solid {self.colors.border};
        }}
        QToolBar {{
            background-color: {self.colors.surface_muted};
            border-bottom: 1px solid {self.colors.border};
            spacing: {self.spacing.toolbar_spacing_px}px;
        }}
        #ribbon {{
            background-color: {self.colors.surface_muted};
            border-bottom: 1px solid {self.colors.border};
        }}
        #ribbonTabs::pane {{
            border: none;
        }}
        #ribbonTabs QTabBar::tab {{
            background-color: {self.colors.brand_primary_soft};
            color: {self.colors.text_primary};
            padding: 6px 14px;
            border: 1px solid {self.colors.border};
            border-bottom: none;
            margin-right: 4px;
            border-top-left-radius: 4px;
            border-top-right-radius: 4px;
        }}
        #ribbonTabs QTabBar::tab:selected {{
            background-color: {self.colors.surface};
            color: {self.colors.brand_primary_dark};
            font-weight: {self.typography.section_weight};
        }}
        #ribbon QToolButton {{
            background-color: {self.colors.surface};
            border: 1px solid {self.colors.border_soft};
            padding: 6px;
            border-radius: {self.radii.button_px}px;
        }}
        #ribbon QToolButton:hover {{
            border-color: {self.colors.brand_primary};
            color: {self.colors.brand_primary};
        }}
        QStatusBar {{
            background-color: {self.colors.surface_muted};
            border-top: 1px solid {self.colors.border};
        }}
        #headerBar {{
            background-color: {self.colors.brand_primary};
        }}
        #appTitle {{
            color: {self.colors.text_inverted};
            font-size: {self.typography.title_size_px}px;
            font-weight: {self.typography.title_weight};
        }}
        #appSubtitle {{
            color: {self.colors.text_muted};
            font-size: {self.typography.subtitle_size_px}px;
            font-weight: {self.typography.subtitle_weight};
        }}
        #modeBadge {{
            background-color: {self.colors.brand_accent};
            color: {self.colors.text_inverted};
            padding: {self.spacing.badge_padding};
            border-radius: {self.radii.badge_px}px;
            font-weight: {self.typography.badge_weight};
        }}
        #modeBadge[danger="true"] {{
            background-color: {self.colors.brand_danger};
        }}
        #modeBadge[danger="false"] {{
            background-color: {self.colors.brand_accent};
        }}
        #sidebar {{
            background-color: {self.colors.surface_alt};
            border-right: 1px solid {self.colors.border};
        }}
        #sidebarTitle {{
            color: {self.colors.text_primary};
            font-weight: {self.typography.section_weight};
            padding: {self.spacing.sidebar_title_padding};
        }}
        QGroupBox {{
            border: 1px solid {self.colors.border};
            border-radius: {self.radii.group_box_px}px;
            margin-top: 12px;
            padding-top: 8px;
            background-color: {self.colors.surface};
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 6px;
            color: {self.colors.text_primary};
            font-weight: {self.typography.section_weight};
        }}
        QTreeView,
        QTableView {{
            border: 1px solid {self.colors.border};
            background-color: {self.colors.surface};
            alternate-background-color: {self.colors.surface_muted};
            selection-background-color: {self.colors.brand_primary};
            selection-color: {self.colors.text_inverted};
        }}
        QLabel {{
            color: {self.colors.text_primary};
        }}
        QPushButton {{
            background-color: {self.colors.surface};
            border: 1px solid {self.colors.border_soft};
            padding: {self.spacing.button_padding};
            border-radius: {self.radii.button_px}px;
            text-align: left;
        }}
        QPushButton:hover {{
            border-color: {self.colors.brand_primary};
            color: {self.colors.brand_primary};
        }}
        QPushButton#primaryAction {{
            background-color: {self.colors.brand_primary};
            border-color: {self.colors.brand_primary};
            color: {self.colors.text_inverted};
            font-weight: {self.typography.section_weight};
        }}
        QPushButton#primaryAction:hover {{
            background-color: {self.colors.brand_primary_dark};
            border-color: {self.colors.brand_primary_dark};
            color: {self.colors.text_inverted};
        }}
        """


AOMEI_THEME = AomeiTheme(
    colors=ThemeColors(
        window_bg="#f5f7fb",
        text_primary="#1f2a44",
        brand_primary="#1e6fd9",
        brand_primary_dark="#1559ad",
        brand_primary_soft="#dbe8ff",
        brand_accent="#1fb456",
        brand_danger="#d94242",
        surface="#ffffff",
        surface_alt="#eef3fb",
        surface_muted="#f0f4fb",
        border="#d9e1f0",
        border_soft="#c7d3ea",
        text_inverted="#ffffff",
        text_muted="#dbe8ff",
    ),
    typography=ThemeTypography(
        title_size_px=18,
        subtitle_size_px=11,
        title_weight=700,
        subtitle_weight=400,
        badge_weight=700,
        section_weight=600,
    ),
    spacing=ThemeSpacing(
        menubar_padding_px=4,
        toolbar_spacing_px=8,
        badge_padding="6px 12px",
        button_padding="6px 10px",
        sidebar_title_padding="4px 0",
    ),
    radii=ThemeRadii(
        group_box_px=6,
        button_px=4,
        badge_px=12,
    ),
)


def aomei_qss() -> str:
    """Return the QSS for the AOMEI theme."""
    return AOMEI_THEME.qss()
