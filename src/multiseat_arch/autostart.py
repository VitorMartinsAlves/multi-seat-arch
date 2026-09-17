from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

UNIT_NAME = "multi-seat-arch-autostart.service"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
TARGET_NAME = "multi-seat-arch.target"
TARGET_PATH = Path("/etc/systemd/system") / TARGET_NAME
CONFIG_PATH = Path("/etc/multi-seat-arch/config.json")
PREVIOUS_TARGET_PATH = Path("/etc/multi-seat-arch/default-target.before-autostart")
FAILURE_MARKER = Path("/var/lib/multi-seat-arch/autostart-disabled-after-failure")

_TARGET_RE = re.compile(r"^[A-Za-z0-9_.@:-]+\.target$")


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def _default_target() -> str:
    result = _run(["systemctl", "get-default"], check=False)
    target = result.stdout.strip()
    return target if _TARGET_RE.fullmatch(target) else "graphical.target"


def _saved_previous_target() -> str:
    try:
        target = PREVIOUS_TARGET_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return "graphical.target"
    if target == TARGET_NAME or not _TARGET_RE.fullmatch(target):
        return "graphical.target"
    return target


def enabled() -> bool:
    if not UNIT_PATH.exists() or not TARGET_PATH.exists():
        return False
    enabled_unit = _run(
        ["systemctl", "is-enabled", "--quiet", UNIT_NAME], check=False
    ).returncode == 0
    return enabled_unit and _default_target() == TARGET_NAME


def _helper_binary() -> str:
    helper = shutil.which("multi-seat-arch")
    if helper:
        return str(Path(helper).resolve())
    for candidate in (
        Path("/usr/bin/multi-seat-arch"),
        Path("/usr/local/bin/multi-seat-arch"),
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError("Executável multi-seat-arch não encontrado no PATH.")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.chmod(tmp, 0o644)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def enable() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    if not CONFIG_PATH.is_file():
        raise RuntimeError("Salve uma configuração válida antes de ativar o início automático.")

    helper = _helper_binary()

    # Do not race the normal graphical boot. exp23 attached the autostart unit to
    # multi-user.target while graphical.target was still part of the same boot
    # transaction. SDDM could therefore start after MSA had acquired the DRM
    # leases and take both outputs back as one desktop. A dedicated default
    # target makes the two boot modes mutually exclusive from PID 1's point of
    # view: normal graphical boot OR Multi Seat Arch boot.
    target = f"""[Unit]
Description=Multi Seat Arch boot mode
Requires=multi-user.target
After=multi-user.target systemd-user-sessions.service
Wants=systemd-user-sessions.service
AllowIsolate=yes
"""
    unit = f"""[Unit]
Description=Multi Seat Arch automatic boot
Requires=multi-user.target
After=multi-user.target systemd-user-sessions.service
Wants=systemd-user-sessions.service
PartOf={TARGET_NAME}
IgnoreOnIsolate=yes
ConditionPathExists={CONFIG_PATH}

[Service]
Type=oneshot
ExecStart={helper} _boot
RemainAfterExit=yes
TimeoutStartSec=240

[Install]
WantedBy={TARGET_NAME}
"""

    current_default = _default_target()
    if current_default != TARGET_NAME and not PREVIOUS_TARGET_PATH.exists():
        _write_atomic(PREVIOUS_TARGET_PATH, current_default + "\n")

    _write_atomic(TARGET_PATH, target)
    _write_atomic(UNIT_PATH, unit)
    FAILURE_MARKER.unlink(missing_ok=True)

    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", UNIT_NAME])
    _run(["systemctl", "set-default", TARGET_NAME])


def disable() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")

    previous = _saved_previous_target()
    _run(["systemctl", "disable", UNIT_NAME], check=False)
    if _default_target() == TARGET_NAME:
        _run(["systemctl", "set-default", previous], check=False)

    try:
        UNIT_PATH.unlink(missing_ok=True)
        TARGET_PATH.unlink(missing_ok=True)
        PREVIOUS_TARGET_PATH.unlink(missing_ok=True)
        FAILURE_MARKER.unlink(missing_ok=True)
    finally:
        _run(["systemctl", "daemon-reload"], check=False)
        _run(["systemctl", "reset-failed", UNIT_NAME], check=False)


def disable_after_boot_failure() -> None:
    """Fail safe: a bad multiseat boot must not trap the next reboot too."""
    if os.geteuid() != 0:
        return
    FAILURE_MARKER.parent.mkdir(parents=True, exist_ok=True)
    try:
        FAILURE_MARKER.write_text(
            "Automatic multiseat boot was disabled after a failed activation.\n",
            encoding="utf-8",
        )
    except OSError:
        pass

    # Keep the files for diagnostics, but make the next boot normal. The user
    # can explicitly enable autostart again after fixing the reported problem.
    _run(["systemctl", "disable", UNIT_NAME], check=False)
    _run(["systemctl", "set-default", _saved_previous_target()], check=False)
    _run(["systemctl", "daemon-reload"], check=False)
