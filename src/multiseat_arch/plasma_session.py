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


def _import_user_manager_environment(timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    wanted = {"WAYLAND_DISPLAY", "DISPLAY", "XAUTHORITY"}
    while time.monotonic() < deadline:
        result = _run(["systemctl", "--user", "show-environment"])
        if result.returncode == 0:
            found: set[str] = set()
            for line in result.stdout.splitlines():
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                if key in wanted and value:
                    os.environ[key] = value
                    found.add(key)
            if "WAYLAND_DISPLAY" in found:
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
        "KDE_FULL_SESSION",
        "KDE_SESSION_VERSION",
    ]
    available = [name for name in names if os.environ.get(name)]
    if shutil.which("dbus-update-activation-environment") and available:
        _run(["dbus-update-activation-environment", "--systemd", *available])
    if shutil.which("systemctl") and available:
        _run(["systemctl", "--user", "import-environment", *available])


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

    _import_user_manager_environment()
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

    if not any(Path(proc.args[0]).name == "plasmashell" for proc in children if isinstance(proc.args, list)):
        return 2

    plasma = next(
        proc
        for proc in children
        if isinstance(proc.args, list) and Path(proc.args[0]).name == "plasmashell"
    )
    return plasma.wait()


if __name__ == "__main__":
    raise SystemExit(main())
