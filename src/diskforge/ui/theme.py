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
        QMenuBar::item:pressed {{
            background-color: {self.colors.brand_primary_dark};
        }}
        QMenuBar::item:disabled {{
            color: {self.colors.text_muted};
        }}
        QMenu {{
            background-color: {self.colors.surface};
            border: 1px solid {self.colors.border};
        }}
        QMenu::item {{
            padding: 6px 18px;
            background-color: transparent;
        }}
        QMenu::item:selected {{
            background-color: {self.colors.brand_primary_soft};
            color: {self.colors.brand_primary_dark};
        }}
        QMenu::item:disabled {{
            color: {self.colors.text_muted};
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
            background-color: {self.colors.surface_muted};
            color: {self.colors.text_primary};
            padding: 6px 16px;
            border: 1px solid {self.colors.border};
            border-bottom: none;
            margin-right: 6px;
            border-top-left-radius: {self.radii.button_px}px;
            border-top-right-radius: {self.radii.button_px}px;
        }}
        #ribbonTabs QTabBar::tab:hover:!selected {{
            background-color: {self.colors.brand_primary_soft};
            color: {self.colors.brand_primary_dark};
        }}
        #ribbonTabs QTabBar::tab:disabled {{
            background-color: {self.colors.surface_muted};
            color: {self.colors.text_muted};
        }}
        #ribbonTabs QTabBar::tab:selected {{
            background-color: {self.colors.surface};
            color: {self.colors.brand_primary_dark};
            font-weight: {self.typography.section_weight};
            border-color: {self.colors.brand_primary};
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
        #ribbon QToolButton:pressed {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
        }}
        #ribbon QToolButton:checked {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
            color: {self.colors.brand_primary_dark};
        }}
        #ribbon QToolButton:disabled {{
            background-color: {self.colors.surface_muted};
            border-color: {self.colors.border};
            color: {self.colors.text_muted};
        }}
        QStatusBar {{
            background-color: {self.colors.surface_muted};
            border-top: 1px solid {self.colors.border};
        }}
        #headerBar {{
            background-color: {self.colors.brand_primary};
            border-bottom: 1px solid {self.colors.brand_primary_dark};
        }}
        #headerBar QLabel {{
            color: {self.colors.text_inverted};
        }}
        #appLogo {{
            background-color: {self.colors.text_inverted};
            color: {self.colors.brand_primary};
            border-radius: 8px;
            font-size: 16px;
            font-weight: {self.typography.title_weight};
        }}
        #appTitle {{
            color: {self.colors.text_inverted};
            font-size: {self.typography.title_size_px}px;
            font-weight: {self.typography.title_weight};
            letter-spacing: 0.4px;
        }}
        #appSubtitle {{
            color: {self.colors.brand_primary_soft};
            font-size: {self.typography.subtitle_size_px}px;
            font-weight: {self.typography.subtitle_weight};
        }}
        #headerActionButton {{
            color: {self.colors.text_inverted};
            border: 1px solid transparent;
            padding: 4px 10px;
            border-radius: {self.radii.button_px}px;
            text-align: center;
        }}
        #headerActionButton:hover {{
            background-color: {self.colors.brand_primary_dark};
            border-color: {self.colors.brand_primary_dark};
        }}
        #headerActionButton:pressed {{
            background-color: {self.colors.brand_primary_dark};
            border-color: {self.colors.brand_primary_dark};
        }}
        #headerActionButton:disabled {{
            color: {self.colors.text_muted};
        }}
        #versionBadge {{
            background-color: {self.colors.text_inverted};
            color: {self.colors.brand_primary_dark};
            padding: 2px 8px;
            border-radius: {self.radii.badge_px}px;
            font-weight: {self.typography.badge_weight};
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
        #diskMapPanel {{
            background-color: {self.colors.surface};
            border: 1px solid {self.colors.border};
            border-radius: {self.radii.group_box_px}px;
        }}
        #sectionTitle {{
            color: {self.colors.text_primary};
            font-weight: {self.typography.section_weight};
            font-size: {self.typography.subtitle_size_px + 2}px;
        }}
        #diskMapSubtitle {{
            color: {self.colors.text_muted};
        }}
        #mapActionButton {{
            background-color: {self.colors.surface_alt};
            border: 1px solid {self.colors.border_soft};
            padding: 4px 10px;
            border-radius: {self.radii.button_px}px;
        }}
        #mapActionButton:hover {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
            color: {self.colors.brand_primary_dark};
        }}
        #mapActionButton:pressed {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
        }}
        #diskLegend QLabel {{
            color: {self.colors.text_primary};
        }}
        #legendLabel {{
            font-weight: {self.typography.section_weight};
        }}
        #legendMeta {{
            color: {self.colors.text_muted};
            font-size: {self.typography.subtitle_size_px}px;
        }}
        #legendTitle {{
            color: {self.colors.text_muted};
            font-weight: {self.typography.section_weight};
        }}
        #legendValue {{
            color: {self.colors.text_primary};
        }}
        #legendEmpty {{
            color: {self.colors.text_muted};
            font-style: italic;
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
        QFrame[frameShape="4"],
        QFrame[frameShape="5"] {{
            background-color: {self.colors.border};
            border: none;
        }}
        QTreeView,
        QTableView {{
            border: 1px solid {self.colors.border};
            background-color: {self.colors.surface};
            alternate-background-color: {self.colors.surface_muted};
            selection-background-color: {self.colors.brand_primary};
            selection-color: {self.colors.text_inverted};
        }}
        QHeaderView::section {{
            background-color: {self.colors.surface_alt};
            color: {self.colors.text_primary};
            padding: 6px 8px;
            border: 1px solid {self.colors.border};
            border-left: none;
        }}
        QHeaderView::section:first {{
            border-left: 1px solid {self.colors.border};
        }}
        QHeaderView::section:hover {{
            background-color: {self.colors.brand_primary_soft};
        }}
        QHeaderView::section:pressed {{
            background-color: {self.colors.brand_primary_soft};
            color: {self.colors.brand_primary_dark};
        }}
        QTableCornerButton::section {{
            background-color: {self.colors.surface_alt};
            border: 1px solid {self.colors.border};
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
        QPushButton:pressed {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
        }}
        QPushButton:checked {{
            background-color: {self.colors.brand_primary_soft};
            border-color: {self.colors.brand_primary};
            color: {self.colors.brand_primary_dark};
        }}
        QPushButton:disabled {{
            background-color: {self.colors.surface_muted};
            border-color: {self.colors.border};
            color: {self.colors.text_muted};
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
        QPushButton#primaryAction:pressed {{
            background-color: {self.colors.brand_primary_dark};
            border-color: {self.colors.brand_primary_dark};
        }}
        QPushButton#primaryAction:disabled {{
            background-color: {self.colors.border};
            border-color: {self.colors.border};
            color: {self.colors.text_muted};
        }}
        QScrollBar:vertical {{
            background-color: {self.colors.surface_muted};
            width: 10px;
            margin: 0;
        }}
        QScrollBar::handle:vertical {{
            background-color: {self.colors.border_soft};
            border-radius: 4px;
            min-height: 20px;
        }}
        QScrollBar::handle:vertical:hover {{
            background-color: {self.colors.brand_primary_soft};
        }}
        QScrollBar::add-line:vertical,
        QScrollBar::sub-line:vertical {{
            height: 0;
        }}
        QScrollBar::add-page:vertical,
        QScrollBar::sub-page:vertical {{
            background: none;
        }}
        QScrollBar:horizontal {{
            background-color: {self.colors.surface_muted};
            height: 10px;
            margin: 0;
        }}
        QScrollBar::handle:horizontal {{
            background-color: {self.colors.border_soft};
            border-radius: 4px;
            min-width: 20px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background-color: {self.colors.brand_primary_soft};
        }}
        QScrollBar::add-line:horizontal,
        QScrollBar::sub-line:horizontal {{
            width: 0;
        }}
        QScrollBar::add-page:horizontal,
        QScrollBar::sub-page:horizontal {{
            background: none;
        }}
        QToolTip {{
            background-color: {self.colors.surface};
            color: {self.colors.text_primary};
            border: 1px solid {self.colors.border};
            padding: 6px 8px;
            border-radius: {self.radii.button_px}px;
        }}
        """


AOMEI_THEME = AomeiTheme(
    colors=ThemeColors(
        window_bg="#f3f6fb",
        text_primary="#1f2a44",
        brand_primary="#1a69d4",
        brand_primary_dark="#1254ad",
        brand_primary_soft="#e3eefc",
        brand_accent="#2cb45f",
        brand_danger="#e05353",
        surface="#ffffff",
        surface_alt="#edf2fa",
        surface_muted="#f4f7fd",
        border="#d5deef",
        border_soft="#c3d0e8",
        text_inverted="#ffffff",
        text_muted="#6f7f9b",
    ),
    typography=ThemeTypography(
        title_size_px=20,
        subtitle_size_px=11,
        title_weight=700,
        subtitle_weight=500,
        badge_weight=600,
        section_weight=600,
    ),
    spacing=ThemeSpacing(
        menubar_padding_px=6,
        toolbar_spacing_px=10,
        badge_padding="4px 10px",
        button_padding="6px 12px",
        sidebar_title_padding="6px 0",
    ),
    radii=ThemeRadii(
        group_box_px=6,
        button_px=4,
        badge_px=10,
    ),
)


def aomei_qss() -> str:
    """Return the QSS for the AOMEI theme."""
    return AOMEI_THEME.qss()
