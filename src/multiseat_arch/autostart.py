from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

UNIT_NAME = "multi-seat-arch-autostart.service"
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
CONFIG_PATH = Path("/etc/multi-seat-arch/config.json")


def _run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=check,
    )


def enabled() -> bool:
    if not UNIT_PATH.exists():
        return False
    return _run(["systemctl", "is-enabled", "--quiet", UNIT_NAME], check=False).returncode == 0


def _helper_binary() -> str:
    helper = shutil.which("multi-seat-arch")
    if helper:
        return str(Path(helper).resolve())
    for candidate in (Path("/usr/bin/multi-seat-arch"), Path("/usr/local/bin/multi-seat-arch")):
        if candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError("Executável multi-seat-arch não encontrado no PATH.")


def enable() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    if not CONFIG_PATH.is_file():
        raise RuntimeError("Salve uma configuração válida antes de ativar o início automático.")

    helper = _helper_binary()
    unit = f"""[Unit]
Description=Multi Seat Arch automatic boot
After=systemd-user-sessions.service systemd-udev-settle.service
Wants=systemd-user-sessions.service
Before=display-manager.service
IgnoreOnIsolate=yes
ConditionPathExists={CONFIG_PATH}

[Service]
Type=oneshot
ExecStart={helper} _boot
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
"""
    UNIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = UNIT_PATH.with_name(f".{UNIT_PATH.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(unit, encoding="utf-8")
        os.chmod(tmp, 0o644)
        tmp.replace(UNIT_PATH)
    finally:
        tmp.unlink(missing_ok=True)

    _run(["systemctl", "daemon-reload"])
    _run(["systemctl", "enable", UNIT_NAME])


def disable() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    _run(["systemctl", "disable", UNIT_NAME], check=False)
    try:
        UNIT_PATH.unlink(missing_ok=True)
    finally:
        _run(["systemctl", "daemon-reload"], check=False)
        _run(["systemctl", "reset-failed", UNIT_NAME], check=False)
