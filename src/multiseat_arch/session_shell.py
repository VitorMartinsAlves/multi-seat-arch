from __future__ import annotations

import configparser
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse

from .theme import apply_kde_like_theme


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
    os.environ.setdefault("QT_STYLE_OVERRIDE", "Breeze")
    os.environ.setdefault("GTK_THEME", "Breeze-Dark")
    os.environ.setdefault("XCURSOR_THEME", "breeze_cursors")
    os.environ.setdefault("XCURSOR_SIZE", "24")
    os.environ.setdefault("MOZ_ENABLE_WAYLAND", "1")
    os.environ.setdefault("NIXOS_OZONE_WL", "1")
    os.environ.setdefault("OZONE_PLATFORM", "wayland")


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
        "QT_STYLE_OVERRIDE",
        "GTK_THEME",
        "XCURSOR_THEME",
        "XCURSOR_SIZE",
        "MOZ_ENABLE_WAYLAND",
        "NIXOS_OZONE_WL",
        "OZONE_PLATFORM",
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
        Path("/usr/share/wallpapers/Next/contents/images/1920x1080.jpg"),
        Path("/usr/share/wallpapers/Next/contents/images/2560x1440.jpg"),
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
    if not current or not Path(_decode_wallpaper(current)).is_file():
        if seed_wallpaper:
            parser.set("Desktop", "Wallpaper", seed_wallpaper)
            parser.set("Desktop", "WallpaperMode", "zoom")
    parser.set("Desktop", "BgColor", "#202124")
    parser.set("Desktop", "FgColor", "#eff0f1")
    profile.parent.mkdir(parents=True, exist_ok=True)
    with profile.open("w", encoding="utf-8") as handle:
        parser.write(handle, space_around_delimiters=False)


def _prepare_pcmanfm_profiles() -> None:
    wallpaper = _plasma_wallpaper() or _fallback_wallpaper()
    for profile_name in ("lxqt", "lxqtwayland"):
        _prepare_pcmanfm_profile(profile_name, wallpaper)


def _ensure_chromium_wayland_flags() -> None:
    """Prefer native Wayland for Chromium-family launchers without clobbering user flags."""
    flags = ("--ozone-platform-hint=auto", "--enable-features=UseOzonePlatform")
    for filename in ("chromium-flags.conf", "chrome-flags.conf"):
        path = Path.home() / ".config" / filename
        try:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
        except OSError:
            continue
        text = existing
        for flag in flags:
            if flag.split("=", 1)[0] in text:
                continue
            if text and not text.endswith("\n"):
                text += "\n"
            text += flag + "\n"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass


def _command_result(command: list[str]) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=8,
            check=False,
        )
        return proc.returncode, proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def _write_session_health() -> None:
    """Record graphics/sandbox readiness from inside the actual seat session."""
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    path = runtime / "multi-seat-arch-health.log"
    lines = [
        f"uid={os.getuid()}",
        f"seat={os.environ.get('XDG_SEAT', '')}",
        f"wayland={os.environ.get('WAYLAND_DISPLAY', '')}",
        f"display={os.environ.get('DISPLAY', '')}",
        f"qt_style={os.environ.get('QT_STYLE_OVERRIDE', '')}",
        f"gtk_theme={os.environ.get('GTK_THEME', '')}",
    ]
    try:
        status = Path("/proc/self/status").read_text(encoding="utf-8")
        for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb", "NoNewPrivs"):
            match = re.search(rf"^{key}:\s*(.+)$", status, flags=re.MULTILINE)
            if match:
                lines.append(f"{key}={match.group(1).strip()}")
    except OSError as exc:
        lines.append(f"status_error={exc}")

    unshare = shutil.which("unshare")
    if unshare:
        code, output = _command_result([unshare, "--user", "--map-root-user", "/usr/bin/true"])
        lines.append(f"unshare_rc={code}")
        if output:
            lines.append(f"unshare_output={output}")

    bwrap = shutil.which("bwrap")
    if bwrap:
        code, output = _command_result(
            [bwrap, "--unshare-user", "--unshare-pid", "--ro-bind", "/", "/", "/usr/bin/true"]
        )
        lines.append(f"bwrap_rc={code}")
        if output:
            lines.append(f"bwrap_output={output}")

    try:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    _ensure_session_environment()
    apply_kde_like_theme()
    _prepare_pcmanfm_profiles()
    _ensure_chromium_wayland_flags()
    _import_activation_environment()
    _write_session_health()

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
