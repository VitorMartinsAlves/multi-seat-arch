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


def _import_matching_xwayland_environment(timeout: float = 5.0) -> None:
    """Import DISPLAY/XAUTHORITY only from this seat's KWin environment.

    Never import WAYLAND_DISPLAY from the user manager: it may be stale from a
    previous Labwc/Plasma session and was the reason one seat repeatedly tried
    to connect to a non-existent Wayland socket. The KWin wrapper publishes its
    activation environment; we only accept XWayland values after the published
    WAYLAND_DISPLAY matches the explicit seat socket passed by the launcher.
    """
    expected_wayland = os.environ.get("MSA_WAYLAND_DISPLAY") or os.environ.get(
        "WAYLAND_DISPLAY", ""
    )
    if not expected_wayland:
        return

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
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
        "KDE_FULL_SESSION",
        "KDE_SESSION_VERSION",
    ]
    available = [name for name in names if os.environ.get(name)]
    if shutil.which("dbus-update-activation-environment") and available:
        _run(["dbus-update-activation-environment", "--systemd", *available])
    if shutil.which("systemctl") and available:
        _run(["systemctl", "--user", "import-environment", *available])


def _refresh_application_database() -> None:
    """Populate KDE's service cache for custom Plasma sessions.

    startplasma normally prepares the XDG data paths and rebuilds KSycoca.
    This project intentionally bypasses startplasma so it can keep the patched
    per-seat KWin instance alive; do the relevant application-cache step here.
    """
    data_dirs = os.environ.get("XDG_DATA_DIRS", "").strip()
    defaults = ["/usr/local/share", "/usr/share"]
    current = [part for part in data_dirs.split(":") if part]
    for item in defaults:
        if item not in current:
            current.append(item)
    os.environ["XDG_DATA_DIRS"] = ":".join(current)

    for candidate in ("kbuildsycoca6", "kbuildsycoca5"):
        binary = shutil.which(candidate)
        if binary:
            _run([binary, "--noincremental"])
            break


def _start_first(candidates: list[str], args: list[str] | None = None) -> subprocess.Popen | None:
    for candidate in candidates:
        binary = shutil.which(candidate)
        if not binary and candidate.startswith("/") and Path(candidate).is_file():
            binary = candidate
        if not binary:
            continue
        try:
            return subprocess.Popen([binary, *(args or [])])
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
    os.environ.setdefault("QT_QPA_PLATFORM", "wayland;xcb")
    os.environ.setdefault("MOZ_ENABLE_WAYLAND", "1")

    expected = os.environ.get("MSA_WAYLAND_DISPLAY")
    if expected:
        # The launcher owns the source of truth. Do not let an old systemd-user
        # environment silently redirect this seat to another compositor.
        os.environ["WAYLAND_DISPLAY"] = expected

    if not _wayland_socket_ready():
        return 3

    _refresh_application_database()
    _import_matching_xwayland_environment()
    _sync_activation_environment()

    # These are the user-facing parts of a normal Plasma session. We avoid
    # startplasma-wayland/plasma-session because they would launch a second,
    # unpatched KWin instance and steal the seat.
    children: list[subprocess.Popen] = []
    for candidates, args in [
        (["kactivitymanagerd"], []),
        (["kded6"], []),
        (["ksmserver"], []),
        (["/usr/lib/polkit-kde-authentication-agent-1", "polkit-kde-authentication-agent-1"], []),
        (["xembedsniproxy"], []),
        (["plasmashell"], ["--replace"]),
        (["krunner"], []),
    ]:
        proc = _start_first(candidates, args)
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
