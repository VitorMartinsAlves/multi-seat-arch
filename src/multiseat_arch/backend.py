from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from .model import Config

@dataclass(slots=True)
class Check:
    ok: bool
    message: str


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _resolve_binary(name: str, fallback: str | None = None) -> str | None:
    found = shutil.which(name)
    if found: return found
    if fallback and Path(fallback).exists(): return fallback
    return None


def doctor(config: Config | None = None) -> list[Check]:
    checks = [
        Check(command_exists("loginctl"), "systemd-logind/loginctl"),
        Check(command_exists("systemd-run"), "systemd-run"),
        Check(command_exists("libinput"), "libinput"),
        Check(command_exists("udevadm"), "udevadm"),
        Check(_resolve_binary("drm-lease-manager", "/usr/local/bin/drm-lease-manager") is not None, "drm-lease-manager"),
    ]
    comp = config.compositor if config else "/usr/local/bin/labwc"
    checks.append(Check(Path(comp).exists() or command_exists(Path(comp).name), f"compositor: {comp}"))
    return checks


def validate(config: Config) -> list[str]:
    errors: list[str] = []
    if len(config.seats) < 2: errors.append("São necessários pelo menos 2 seats.")
    connectors: set[str] = set(); inputs: set[str] = set(); names: set[str] = set()
    for seat in config.seats:
        if not seat.name.startswith("seat-"): errors.append(f"Seat '{seat.name}' deve começar com 'seat-'.")
        if seat.name in names: errors.append(f"Seat duplicado: {seat.name}")
        names.add(seat.name)
        if seat.connector in connectors: errors.append(f"Conector usado por mais de um seat: {seat.connector}")
        connectors.add(seat.connector)
        connector_path = Path(seat.connector if seat.connector.startswith("/sys/") else f"/sys/class/drm/{seat.connector}")
        if not connector_path.exists(): errors.append(f"Conector não encontrado: {seat.connector}")
        try: pwd.getpwnam(seat.user)
        except KeyError: errors.append(f"Usuário inexistente: {seat.user}")
        if not seat.inputs: errors.append(f"{seat.name} não possui dispositivos de entrada.")
        for syspath in seat.inputs:
            if syspath in inputs: errors.append(f"Input atribuído a mais de um seat: {syspath}")
            inputs.add(syspath)
            if not syspath.startswith("/sys/devices/"): errors.append(f"Syspath de input inválido: {syspath}")
            elif not Path(syspath).exists(): errors.append(f"Input não encontrado: {syspath}")
    if not Path(config.compositor).exists() and not command_exists(Path(config.compositor).name):
        errors.append(f"Compositor não encontrado: {config.compositor}")
    return errors


def _run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)


def attach_inputs(config: Config) -> None:
    for seat in config.seats:
        for syspath in seat.inputs:
            _run(["loginctl", "attach", seat.name, syspath])


def flush_inputs() -> None:
    _run(["loginctl", "flush-devices"], check=False)
    _run(["udevadm", "control", "--reload"], check=False)
    _run(["udevadm", "trigger", "--subsystem-match=input"], check=False)


def stop_display_manager() -> None:
    _run(["systemctl", "stop", "display-manager.service"], check=False)


def start_display_manager() -> None:
    _run(["systemctl", "start", "display-manager.service"], check=False)


def stop_transient_units() -> None:
    out = _run(["systemctl", "list-units", "--all", "--plain", "--no-legend"], check=False).stdout
    for line in out.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if unit.startswith(("msa-seat-", "msa-dlm-")):
            _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed"], check=False)


def _wait_for_lease(lease: str, uid: int, timeout: float = 12.0) -> None:
    base = Path("/var/local/run/drm-lease-manager")
    lease_path = base / lease; lock_path = base / f"{lease}.lock"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if lease_path.exists() and lock_path.exists():
            os.chown(lease_path, uid, -1); os.chown(lock_path, uid, -1); return
        time.sleep(0.15)
    raise RuntimeError(f"DRM lease não apareceu para {lease} em {timeout:.0f}s")


def start(config: Config) -> None:
    if os.geteuid() != 0: raise PermissionError("Execute como root.")
    errors = validate(config)
    if errors: raise RuntimeError("\n".join(errors))
    missing = [c.message for c in doctor(config) if not c.ok]
    if missing: raise RuntimeError("Dependências ausentes: " + ", ".join(missing))

    stop_transient_units(); stop_display_manager(); attach_inputs(config)
    dlm = _resolve_binary("drm-lease-manager", "/usr/local/bin/drm-lease-manager")
    assert dlm is not None
    cards = sorted({seat.connector.split("-", 1)[0] for seat in config.seats})
    for card in cards:
        _run(["systemd-run", f"--unit=msa-dlm-{card}", "--property=Restart=on-failure", dlm, f"/dev/dri/{card}"])

    for seat in config.seats:
        uid = pwd.getpwnam(seat.user).pw_uid
        _wait_for_lease(seat.connector, uid)
        envs = [
            f"--setenv=XDG_SEAT={seat.name}", f"--setenv=DRM_LEASE={seat.connector}",
            "--setenv=XDG_SESSION_TYPE=wayland", "--setenv=SEATD_VTBOUND=0",
            "--setenv=WLR_LIBINPUT_NO_DEVICES=1",
        ]
        _run(["systemd-run", f"--unit=msa-seat-{seat.name}", f"--uid={uid}",
              "--property=PAMName=login", "--property=Restart=on-failure", "--property=RestartSec=1s",
              *envs, config.compositor])


def restore() -> None:
    if os.geteuid() != 0: raise PermissionError("Execute como root.")
    stop_transient_units(); flush_inputs(); start_display_manager()
