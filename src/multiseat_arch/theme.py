from __future__ import annotations

import configparser
import shutil
from pathlib import Path

THEME_VERSION = "kde-like-v1"

PANEL_CONFIG = """# Generated once by multi-seat-arch. Edit freely after first start.
panels=panel1

[panel1]
plugins=mainmenu,quicklaunch,taskbar,statusnotifier,tray,volume,worldclock,showdesktop
position=Bottom
alignment=Left
size=42
length=100
lengthInPercents=true
hidable=false

[mainmenu]
type=mainmenu
showIconButton=true

[quicklaunch]
type=quicklaunch
alignment=Left

[taskbar]
type=taskbar
alignment=Left
buttonWidth=190
closeOnMiddleClick=true
groupingEnabled=true
showIcon=true
showTitle=true
raiseOnClick=true

[statusnotifier]
type=statusnotifier
alignment=Right

[tray]
type=tray
alignment=Right

[volume]
type=volume
alignment=Right

[worldclock]
type=worldclock
alignment=Right
formatType=custom
useAdvancedManualFormat=true
customFormat=HH:mm
showTooltip=true

[showdesktop]
type=showdesktop
alignment=Right
"""


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _backup_once(path: Path) -> None:
    if not path.exists():
        return
    backup = path.with_name(path.name + ".msa-backup")
    if not backup.exists():
        try:
            shutil.copy2(path, backup)
        except OSError:
            pass


def _write_lxqt_appearance(path: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if path.exists():
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str

    for section in ("General", "Qt", "Palette"):
        if not parser.has_section(section):
            parser.add_section(section)

    # LXQt shell theme + KDE visual language.
    parser.set("General", "theme", "dark")
    parser.set("General", "icon_theme", "breeze-dark")
    parser.set("Qt", "style", "Breeze")

    # Plasma/Breeze-like dark palette. These values are harmless when the Qt
    # style provides its own palette, but keep fallback widgets consistent.
    colors = {
        "window_color": "#202124",
        "window_text_color": "#eff0f1",
        "base_color": "#1b1c1f",
        "text_color": "#eff0f1",
        "button_color": "#292a2d",
        "button_text_color": "#eff0f1",
        "highlight_color": "#3daee9",
        "highlighted_text_color": "#ffffff",
        "link_color": "#3daee9",
        "link_visited_color": "#9b59b6",
        "tooltip_base_color": "#31363b",
        "tooltip_text_color": "#eff0f1",
    }
    for key, value in colors.items():
        parser.set("Palette", key, value)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        parser.write(handle, space_around_delimiters=False)


def _write_qterminal_theme(path: Path) -> None:
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if path.exists():
        try:
            parser.read(path, encoding="utf-8")
        except (OSError, configparser.Error):
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
    if not parser.has_section("General"):
        parser.add_section("General")
    parser.set("General", "colorScheme", "Linux")
    parser.set("General", "fontFamily", "Noto Sans Mono")
    parser.set("General", "fontSize", "11")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        parser.write(handle, space_around_delimiters=False)


def apply_kde_like_theme(home: Path | None = None) -> bool:
    """Seed a KDE-like LXQt profile for any seat user.

    The profile is applied once per theme version and per user. Existing files
    are backed up on first adoption, then users are free to customize them.
    This makes the behavior independent of fixed usernames or seat count.
    """
    home = home or Path.home()
    marker = home / ".config/multi-seat-arch/theme-version"
    try:
        if marker.read_text(encoding="utf-8").strip() == THEME_VERSION:
            return False
    except OSError:
        pass

    lxqt = home / ".config/lxqt/lxqt.conf"
    panel = home / ".config/lxqt/panel.conf"
    qterminal = home / ".config/qterminal.org/qterminal.ini"

    for path in (lxqt, panel, qterminal):
        _backup_once(path)

    _write_lxqt_appearance(lxqt)
    _atomic_write(panel, PANEL_CONFIG)
    _write_qterminal_theme(qterminal)
    _atomic_write(marker, THEME_VERSION + "\n")
    return True
