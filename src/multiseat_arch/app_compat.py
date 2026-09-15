from __future__ import annotations

import configparser
import os
import re
import shutil
from pathlib import Path

CHROMIUM_FLAG_PREFIXES = (
    "--ozone-platform",
    "--enable-features=UseOzonePlatform",
)

POWER_NAME_WORDS = {
    "desligar",
    "reiniciar",
    "suspender",
    "hibernar",
    "sair",
    "logout",
    "log out",
    "shutdown",
    "reboot",
    "suspend",
    "hibernate",
}


def _clean_flag_file(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    kept = [line for line in lines if not any(line.strip().startswith(prefix) for prefix in CHROMIUM_FLAG_PREFIXES)]
    try:
        path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    except OSError:
        pass


def prefer_xwayland_for_chromium(home: Path | None = None) -> None:
    home = home or Path.home()
    for name in (
        "chrome-flags.conf",
        "chromium-flags.conf",
        "brave-flags.conf",
        "microsoft-edge-flags.conf",
        "vivaldi-stable.conf",
    ):
        _clean_flag_file(home / ".config" / name)
    for name in ("OZONE_PLATFORM", "NIXOS_OZONE_WL", "ELECTRON_OZONE_PLATFORM_HINT"):
        os.environ.pop(name, None)


def _desktop_name_and_exec(path: Path) -> tuple[str, str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return "", ""
    if not parser.has_section("Desktop Entry"):
        return "", ""
    section = parser["Desktop Entry"]
    names = [value for key, value in section.items() if key == "Name" or key.startswith("Name[")]
    return " ".join(names).lower(), section.get("Exec", "").lower()


def _is_fake_power_launcher(path: Path) -> bool:
    name, command = _desktop_name_and_exec(path)
    if not name:
        return False
    named_power = any(word in name for word in POWER_NAME_WORDS)
    command_power = bool(re.search(r"\b(poweroff|reboot|shutdown|hibernate|suspend|logout|lxqt-leave|loginctl)\b", command))
    return named_power and command_power


def hide_power_pseudo_apps(home: Path | None = None) -> int:
    home = home or Path.home()
    target = home / ".local/share/applications"
    target.mkdir(parents=True, exist_ok=True)
    count = 0
    for root in (Path("/usr/share/applications"), Path("/usr/local/share/applications")):
        if not root.is_dir():
            continue
        for source in root.glob("*.desktop"):
            if not _is_fake_power_launcher(source):
                continue
            try:
                (target / source.name).write_text(
                    "[Desktop Entry]\nType=Application\nHidden=true\nNoDisplay=true\n",
                    encoding="utf-8",
                )
                count += 1
            except OSError:
                pass
    return count


def create_session_launcher(home: Path | None = None) -> Path:
    home = home or Path.home()
    path = home / ".local/share/applications/multi-seat-session.desktop"
    path.parent.mkdir(parents=True, exist_ok=True)
    binary = shutil.which("lxqt-leave") or "/usr/bin/lxqt-leave"
    path.write_text(
        "[Desktop Entry]\nType=Application\nName=Sessão\n"
        "Comment=Bloquear, sair, reiniciar ou desligar\n"
        f"Exec={binary}\nIcon=system-shutdown\nTerminal=false\nCategories=System;\n",
        encoding="utf-8",
    )
    return path
