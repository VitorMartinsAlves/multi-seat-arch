from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from .app_compat import create_session_launcher, hide_power_pseudo_apps, prefer_xwayland_for_chromium
from .theme import restore_native_lxqt_theme


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _ensure_session_environment() -> None:
    uid = os.getuid()
    runtime = Path(f"/run/user/{uid}")
    if not os.environ.get("XDG_RUNTIME_DIR") and runtime.is_dir():
        os.environ["XDG_RUNTIME_DIR"] = str(runtime)
    bus = runtime / "bus"
    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS") and bus.exists():
        os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={bus}"

    os.environ.setdefault("XDG_CURRENT_DESKTOP", "LXQt")
    os.environ.setdefault("XDG_SESSION_DESKTOP", "LXQt")
    os.environ.setdefault("XDG_SESSION_TYPE", "wayland")
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    os.environ.setdefault("MOZ_ENABLE_WAYLAND", "1")


def _import_activation_environment() -> None:
    names = [
        "WAYLAND_DISPLAY",
        "DISPLAY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "XDG_SESSION_TYPE",
        "XDG_SEAT",
        "QT_QPA_PLATFORM",
        "MOZ_ENABLE_WAYLAND",
    ]
    available = [name for name in names if os.environ.get(name)]
    if not available:
        return
    if shutil.which("dbus-update-activation-environment"):
        _run(["dbus-update-activation-environment", "--systemd", *available])
    if shutil.which("systemctl"):
        _run(["systemctl", "--user", "import-environment", *available])


def _decode_wallpaper(value: str) -> str:
    value = value.strip()
    if value.startswith("file://"):
        parsed = urlparse(value)
        return unquote(parsed.path)
    return unquote(value)


def _plasma_wallpaper() -> str | None:
    config = Path.home() / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    try:
        text = config.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for match in re.finditer(r"^Image=(.+)$", text, flags=re.MULTILINE):
        value = _decode_wallpaper(match.group(1))
        if value and Path(value).is_file():
            return value
    return None


def _fallback_wallpaper() -> str | None:
    candidates = [
        Path("/usr/share/lxqt/wallpapers/origami-dark-labwc.png"),
        Path("/usr/share/lxqt/wallpapers/waves-logo.png"),
        Path("/usr/share/backgrounds"),
        Path("/usr/share/wallpapers"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
        if candidate.is_dir():
            for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                try:
                    found = next(candidate.rglob(pattern))
                except StopIteration:
                    continue
                if found.is_file():
                    return str(found)
    return None


def _prepare_pcmanfm_profile(profile_name: str, seed_wallpaper: str | None) -> None:
    """Seed only a missing wallpaper; leave all visual choices to LXQt/PCManFM."""
    profile = Path.home() / f".config/pcmanfm-qt/{profile_name}/settings.conf"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    if profile.exists():
        try:
            parser.read(profile, encoding="utf-8")
        except (OSError, configparser.Error):
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
    if not parser.has_section("Desktop"):
        parser.add_section("Desktop")

    current = parser.get("Desktop", "Wallpaper", fallback="").strip()
    if (not current or not Path(_decode_wallpaper(current)).is_file()) and seed_wallpaper:
        parser.set("Desktop", "Wallpaper", seed_wallpaper)
        parser.set("Desktop", "WallpaperMode", "zoom")

    profile.parent.mkdir(parents=True, exist_ok=True)
    with profile.open("w", encoding="utf-8") as handle:
        parser.write(handle, space_around_delimiters=False)


def _prepare_pcmanfm_profiles() -> None:
    wallpaper = _plasma_wallpaper() or _fallback_wallpaper()
    for profile_name in ("lxqt", "lxqtwayland"):
        _prepare_pcmanfm_profile(profile_name, wallpaper)


def _command_result(command: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=8, check=False)
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _write_session_health() -> None:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    path = runtime / "multi-seat-arch-health.log"
    lines = [
        f"uid={os.getuid()}",
        f"seat={os.environ.get('XDG_SEAT', '')}",
        f"wayland={os.environ.get('WAYLAND_DISPLAY', '')}",
        f"display={os.environ.get('DISPLAY', '')}",
    ]
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs"):
            match = re.search(rf"^{key}:\s*(.+)$", status, flags=re.MULTILINE)
            if match:
                lines.append(f"{key}={match.group(1).strip()}")
    except OSError as exc:
        lines.append(f"status_error={exc}")
    for name in ("unshare", "bwrap"):
        binary = shutil.which(name)
        if not binary:
            continue
        command = [binary, "--user", "--map-root-user", "/usr/bin/true"] if name == "unshare" else [binary, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "/usr/bin/true"]
        code, output = _command_result(command)
        lines.append(f"{name}_rc={code}")
        if output:
            lines.append(f"{name}_output={output}")
    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    _ensure_session_environment()
    prefer_xwayland_for_chromium()
    create_session_launcher()
    hide_power_pseudo_apps()
    restore_native_lxqt_theme()
    _prepare_pcmanfm_profiles()
    _import_activation_environment()
    _write_session_health()

    if shutil.which("update-desktop-database"):
        _run(["update-desktop-database", str(Path.home() / ".local/share/applications")])

    lxqt_session = shutil.which("lxqt-session")
    if lxqt_session:
        os.execv(lxqt_session, [lxqt_session])

    children: list[subprocess.Popen] = []
    for command in (["pcmanfm-qt", "--desktop"], ["lxqt-panel"], ["qterminal"]):
        binary = shutil.which(command[0])
        if binary:
            try:
                children.append(subprocess.Popen([binary, *command[1:]]))
            except OSError:
                pass
    if not children:
        return 1
    return children[0].wait()


if __name__ == "__main__":
    raise SystemExit(main())
