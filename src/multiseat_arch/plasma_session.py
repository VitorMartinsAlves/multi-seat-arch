from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(command, 127, "")


def _import_matching_xwayland_environment(timeout: float = 0.0) -> None:
    """Import X11 values only when this seat's KWin has published them.

    Plasma itself must not wait for XWayland. A broken XWayland instance on one
    seat previously delayed the desktop and made KDE processes try a dead
    DISPLAY. Wayland is the primary session; X11 support is optional.
    """
    expected_wayland = os.environ.get("MSA_WAYLAND_DISPLAY") or os.environ.get(
        "WAYLAND_DISPLAY", ""
    )
    if not expected_wayland:
        return

    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        result = _run(["systemctl", "--user", "show-environment"])
        if result.returncode == 0:
            values: dict[str, str] = {}
            for line in result.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in {"WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"} and value:
                    values[key] = value

            if values.get("WAYLAND_DISPLAY") == expected_wayland:
                for key in ("DISPLAY", "XAUTHORITY"):
                    if values.get(key):
                        os.environ[key] = values[key]
                return

        if time.monotonic() >= deadline:
            return
        time.sleep(0.2)


def _sync_activation_environment() -> None:
    names = [
        "WAYLAND_DISPLAY",
        "DISPLAY",
        "XAUTHORITY",
        "DBUS_SESSION_BUS_ADDRESS",
        "XDG_RUNTIME_DIR",
        "XDG_CURRENT_DESKTOP",
        "XDG_SESSION_DESKTOP",
        "XDG_SESSION_TYPE",
        "XDG_SEAT",
        "XDG_DATA_DIRS",
        "XDG_CONFIG_DIRS",
        "XDG_MENU_PREFIX",
        "KDE_FULL_SESSION",
        "KDE_SESSION_VERSION",
    ]
    available = [name for name in names if os.environ.get(name)]
    if shutil.which("dbus-update-activation-environment") and available:
        _run(["dbus-update-activation-environment", "--systemd", *available])
    if shutil.which("systemctl") and available:
        _run(["systemctl", "--user", "import-environment", *available])


def _prepare_plasma_xdg_environment() -> None:
    data_dirs = [part for part in os.environ.get("XDG_DATA_DIRS", "").split(":") if part]
    for item in ("/usr/local/share", "/usr/share"):
        if item not in data_dirs:
            data_dirs.append(item)
    os.environ["XDG_DATA_DIRS"] = ":".join(data_dirs)

    config_dirs = [part for part in os.environ.get("XDG_CONFIG_DIRS", "").split(":") if part]
    if "/etc/xdg" not in config_dirs:
        config_dirs.append("/etc/xdg")
    os.environ["XDG_CONFIG_DIRS"] = ":".join(config_dirs)

    # Plasma ships plasma-applications.menu. Without the prefix KService can
    # build a valid cache but Kickoff ends up with an empty application tree.
    os.environ["XDG_MENU_PREFIX"] = "plasma-"


def _refresh_application_database() -> None:
    for candidate in ("kbuildsycoca6", "kbuildsycoca5"):
        binary = shutil.which(candidate)
        if binary:
            _run([binary, "--noincremental"])
            break


def _start_first(
    candidates: list[str],
    args: list[str] | None = None,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.Popen | None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    for candidate in candidates:
        binary = shutil.which(candidate)
        if not binary and candidate.startswith("/") and Path(candidate).is_file():
            binary = candidate
        if not binary:
            continue
        try:
            return subprocess.Popen([binary, *(args or [])], env=env)
        except OSError:
            continue
    return None


def _wayland_socket_ready() -> bool:
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    display = os.environ.get("WAYLAND_DISPLAY", "")
    return bool(display and (runtime / display).exists())


def main() -> int:
    runtime = Path(f"/run/user/{os.getuid()}")
    os.environ.setdefault("XDG_RUNTIME_DIR", str(runtime))
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime}/bus")
    os.environ["XDG_CURRENT_DESKTOP"] = "KDE"
    os.environ["XDG_SESSION_DESKTOP"] = "KDE"
    os.environ["XDG_SESSION_TYPE"] = "wayland"
    os.environ["KDE_FULL_SESSION"] = "true"
    os.environ["KDE_SESSION_VERSION"] = "6"
    os.environ["MOZ_ENABLE_WAYLAND"] = "1"

    # Core Plasma must always attach to the per-seat Wayland compositor even if
    # XWayland for that seat is missing or crashing.
    os.environ["QT_QPA_PLATFORM"] = "wayland"

    expected = os.environ.get("MSA_WAYLAND_DISPLAY")
    if expected:
        os.environ["WAYLAND_DISPLAY"] = expected

    if not _wayland_socket_ready():
        return 3

    _prepare_plasma_xdg_environment()
    _refresh_application_database()

    # Do not block desktop startup waiting for XWayland. If it is already
    # available, publish DISPLAY for later-launched legacy applications.
    _import_matching_xwayland_environment(timeout=0.0)
    _sync_activation_environment()

    children: list[subprocess.Popen] = []
    for candidates, args in [
        (["kactivitymanagerd"], []),
        (["kded6"], []),
        (["ksmserver"], []),
        (["/usr/lib/polkit-kde-authentication-agent-1", "polkit-kde-authentication-agent-1"], []),
        (["plasmashell"], ["--replace"]),
        (["krunner"], []),
    ]:
        proc = _start_first(candidates, args, extra_env={"QT_QPA_PLATFORM": "wayland"})
        if proc is not None:
            children.append(proc)

    # xembedsniproxy only has a purpose when an X11 display exists. Starting it
    # against a dead DISPLAY creates noise and can make the session look broken.
    if os.environ.get("DISPLAY"):
        proc = _start_first(["xembedsniproxy"], [], extra_env={"QT_QPA_PLATFORM": "xcb"})
        if proc is not None:
            children.append(proc)

    if not any(
        Path(proc.args[0]).name == "plasmashell"
        for proc in children
        if isinstance(proc.args, list)
    ):
        return 2

    plasma = next(
        proc
        for proc in children
        if isinstance(proc.args, list) and Path(proc.args[0]).name == "plasmashell"
    )
    return plasma.wait()


if __name__ == "__main__":
    raise SystemExit(main())
