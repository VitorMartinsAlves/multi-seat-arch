from __future__ import annotations

import os
import pwd
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .discovery import connector_lease_name
from .model import Config

ACTIVATE_UNIT = "msa-activate.service"
RESTORE_UNIT = "msa-restore.service"
UNIT_PREFIXES = ("msa-seat-", "msa-app-", "msa-dlm-")
LEGACY_UNIT_PREFIXES = ("multiseat-card", "dlm-card")


@dataclass(slots=True)
class Check:
    ok: bool
    message: str


def command_exists(name: str) -> bool:
    return shutil.which(name) is not None


def _resolve_binary(name: str, fallback: str | None = None) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    if fallback and Path(fallback).is_file():
        return fallback
    return None


def _run(
    cmd: list[str],
    check: bool = True,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        text=True,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )


def _ldd_missing(binary: str) -> list[str]:
    if not command_exists("ldd"):
        return ["ldd não encontrado"]
    output = _run(["ldd", binary], check=False).stdout
    return [line.strip() for line in output.splitlines() if "not found" in line]


def doctor(config: Config | None = None) -> list[Check]:
    checks = [
        Check(command_exists("systemctl"), "systemctl"),
        Check(command_exists("systemd-run"), "systemd-run"),
        Check(command_exists("loginctl"), "systemd-logind/loginctl"),
        Check(command_exists("udevadm"), "udevadm"),
        Check(command_exists("ldd"), "ldd"),
    ]

    dlm = _resolve_binary("drm-lease-manager", "/usr/local/bin/drm-lease-manager")
    checks.append(Check(dlm is not None, "drm-lease-manager"))
    if dlm:
        missing = _ldd_missing(dlm)
        checks.append(
            Check(
                not missing,
                "bibliotecas do drm-lease-manager"
                if not missing
                else "drm-lease-manager: " + "; ".join(missing),
            )
        )

    comp = config.compositor if config else "/usr/local/bin/labwc"
    comp_path = (
        str(Path(comp))
        if Path(comp).is_file()
        else _resolve_binary(Path(comp).name)
    )
    checks.append(Check(comp_path is not None, f"compositor: {comp}"))
    if comp_path:
        missing = _ldd_missing(comp_path)
        checks.append(
            Check(
                not missing,
                "bibliotecas do compositor"
                if not missing
                else "compositor: " + "; ".join(missing),
            )
        )

    if command_exists("systemctl"):
        legacy = _run(
            ["systemctl", "is-active", "--quiet", "multiseat.service"],
            check=False,
        ).returncode == 0
        checks.append(
            Check(
                not legacy,
                "serviço legado multiseat.service não está ativo"
                if not legacy
                else "serviço legado multiseat.service está ativo",
            )
        )
    return checks


def validate(config: Config) -> list[str]:
    errors: list[str] = []
    if config.version != 1:
        errors.append(f"Versão de configuração não suportada: {config.version}")
    if len(config.seats) < 2:
        errors.append("São necessários pelo menos 2 seats.")

    connectors: set[str] = set()
    inputs: set[str] = set()
    names: set[str] = set()
    users: set[str] = set()

    for seat in config.seats:
        if not re.fullmatch(r"seat-[A-Za-z0-9_-]+", seat.name):
            errors.append(f"Nome de seat inválido: {seat.name}")
        if seat.name in names:
            errors.append(f"Seat duplicado: {seat.name}")
        names.add(seat.name)

        try:
            connector_lease_name(seat.connector)
        except ValueError as exc:
            errors.append(str(exc))
        if seat.connector in connectors:
            errors.append(
                f"Conector usado por mais de um seat: {seat.connector}"
            )
        connectors.add(seat.connector)

        connector_path = Path("/sys/class/drm") / seat.connector
        if not connector_path.exists():
            errors.append(f"Conector não encontrado: {seat.connector}")
        else:
            try:
                status = (connector_path / "status").read_text(
                    encoding="utf-8"
                ).strip()
            except OSError:
                status = ""
            if status and status != "connected":
                errors.append(f"Conector não está conectado: {seat.connector}")

        try:
            user = pwd.getpwnam(seat.user)
            if user.pw_uid < 1000:
                errors.append(
                    f"Usuário de sistema/root não pode ser usado no seat: {seat.user}"
                )
        except KeyError:
            errors.append(f"Usuário inexistente: {seat.user}")
        if seat.user in users:
            errors.append(
                "Use usuários diferentes por seat para evitar conflito "
                f"de XDG_RUNTIME_DIR: {seat.user}"
            )
        users.add(seat.user)

        if not seat.inputs:
            errors.append(f"{seat.name} não possui dispositivos de entrada.")
        for syspath in seat.inputs:
            if syspath in inputs:
                errors.append(f"Input atribuído a mais de um seat: {syspath}")
            inputs.add(syspath)
            if not syspath.startswith("/sys/devices/"):
                errors.append(f"Syspath de input inválido: {syspath}")
            elif not Path(syspath).exists():
                errors.append(f"Input não encontrado: {syspath}")

    comp_path = Path(config.compositor)
    if not comp_path.is_file() and not command_exists(comp_path.name):
        errors.append(f"Compositor não encontrado: {config.compositor}")

    return errors


def flush_inputs() -> None:
    _run(["loginctl", "flush-devices"], check=False)
    _run(["udevadm", "control", "--reload"], check=False)
    _run(["udevadm", "trigger", "--subsystem-match=input"], check=False)
    _run(["udevadm", "settle", "--timeout=5"], check=False)


def _udev_seat(syspath: str) -> str:
    output = _run(
        ["udevadm", "info", "--query=property", "--path", syspath],
        check=False,
    ).stdout
    for line in output.splitlines():
        if line.startswith("ID_SEAT="):
            return line.split("=", 1)[1].strip()
    return "seat0"


def attach_inputs(config: Config, timeout: float = 4.0) -> None:
    for seat in config.seats:
        for syspath in seat.inputs:
            _run(["loginctl", "attach", seat.name, syspath])
    _run(["udevadm", "settle", "--timeout=5"], check=False)

    deadline = time.monotonic() + timeout
    pending = {
        (seat.name, syspath)
        for seat in config.seats
        for syspath in seat.inputs
    }
    while pending and time.monotonic() < deadline:
        pending = {
            (seat, syspath)
            for seat, syspath in pending
            if _udev_seat(syspath) != seat
        }
        if pending:
            time.sleep(0.1)

    if pending:
        detail = ", ".join(f"{path} -> {seat}" for seat, path in sorted(pending))
        raise RuntimeError(
            "Falha ao atribuir dispositivos de entrada aos seats: " + detail
        )


def stop_transient_units(
    *,
    exclude: set[str] | None = None,
    include_legacy: bool = True,
) -> None:
    exclude = exclude or set()
    out = _run(
        ["systemctl", "list-units", "--all", "--plain", "--no-legend"],
        check=False,
    ).stdout
    prefixes = UNIT_PREFIXES + (LEGACY_UNIT_PREFIXES if include_legacy else ())
    units: list[str] = []
    for line in out.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if unit and unit not in exclude and unit.startswith(prefixes):
            units.append(unit)

    units.sort(key=lambda unit: unit.startswith("msa-dlm-"))
    for unit in units:
        _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed"], check=False)
    _run(["systemctl", "daemon-reload"], check=False)


def _lease_runtime_dirs() -> list[Path]:
    return [
        Path("/var/local/run/drm-lease-manager"),
        Path("/var/run/drm-lease-manager"),
    ]


def _wait_for_lease(lease: str, uid: int, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for base in _lease_runtime_dirs():
            lease_path = base / lease
            lock_path = base / f"{lease}.lock"
            if lease_path.exists() and lock_path.exists():
                os.chown(lease_path, uid, -1)
                os.chown(lock_path, uid, -1)
                return
        time.sleep(0.15)
    raise RuntimeError(
        f"DRM lease '{lease}' não apareceu em {timeout:.0f}s"
    )


def _unit_active(unit: str) -> bool:
    return (
        _run(["systemctl", "is-active", "--quiet", unit], check=False).returncode
        == 0
    )


def _unit_failed(unit: str) -> bool:
    return (
        _run(["systemctl", "is-failed", "--quiet", unit], check=False).returncode
        == 0
    )


def _unit_log_tail(unit: str, lines: int = 30) -> str:
    return _run(
        [
            "journalctl",
            "-u",
            unit,
            "-b",
            "--no-pager",
            "-n",
            str(lines),
        ],
        check=False,
    ).stdout.strip()


def _wait_for_wayland(
    uid: int,
    unit: str,
    timeout: float = 12.0,
) -> str:
    runtime = Path(f"/run/user/{uid}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sockets = sorted(runtime.glob("wayland-*"))
        sockets = [
            path
            for path in sockets
            if not path.name.endswith(".lock")
            and path.exists()
            and path.stat().st_uid == uid
        ]
        if sockets and _unit_active(unit):
            return sockets[0].name
        if _unit_failed(unit):
            log = _unit_log_tail(unit)
            raise RuntimeError(
                f"Compositor falhou em {unit}."
                + (f"\n{log}" if log else "")
            )
        time.sleep(0.15)
    raise RuntimeError(
        f"Compositor não criou socket Wayland em {timeout:.0f}s ({unit})."
    )


def _keyboard_layout() -> str:
    output = _run(["localectl", "status"], check=False).stdout
    for line in output.splitlines():
        if "X11 Layout:" in line:
            layout = line.split(":", 1)[1].strip()
            if layout:
                return layout.split(",", 1)[0]
    return "us"


def _systemd_run(
    unit: str,
    command: list[str],
    *,
    uid: int | None = None,
    env: dict[str, str] | None = None,
    properties: list[str] | None = None,
    no_block: bool = False,
) -> None:
    cmd = ["systemd-run", f"--unit={unit}", "--collect"]
    if no_block:
        cmd.append("--no-block")
    if uid is not None:
        cmd.append(f"--uid={uid}")
    for key, value in (env or {}).items():
        cmd.append(f"--setenv={key}={value}")
    for prop in properties or []:
        cmd.append(f"--property={prop}")
    cmd.extend(command)
    _run(cmd)


def _start_user_apps(
    seat_name: str,
    uid: int,
    wayland_display: str,
) -> None:
    env = {
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "labwc",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "WAYLAND_DISPLAY": wayland_display,
        "DBUS_SESSION_BUS_ADDRESS": f"unix:path=/run/user/{uid}/bus",
    }
    apps = [
        ("desktop", ["pcmanfm-qt", "--desktop"]),
        ("terminal", ["xfce4-terminal"]),
    ]
    for suffix, app in apps:
        binary = _resolve_binary(app[0])
        if not binary:
            continue
        _systemd_run(
            f"msa-app-{seat_name}-{suffix}",
            [binary, *app[1:]],
            uid=uid,
            env=env,
            properties=[
                f"After=msa-seat-{seat_name}.service",
                f"PartOf=msa-seat-{seat_name}.service",
            ],
        )


def _start_seat(config: Config, seat_index: int) -> None:
    seat = config.seats[seat_index]
    account = pwd.getpwnam(seat.user)
    uid = account.pw_uid

    _wait_for_lease(seat.connector, uid)

    compositor = (
        config.compositor
        if Path(config.compositor).is_file()
        else _resolve_binary(Path(config.compositor).name)
    )
    if not compositor:
        raise RuntimeError(f"Compositor não encontrado: {config.compositor}")

    env = {
        "XDG_SEAT": seat.name,
        "DRM_LEASE": seat.connector,
        "XDG_SESSION_TYPE": "wayland",
        "SEATD_VTBOUND": "0",
        "XKB_DEFAULT_LAYOUT": _keyboard_layout(),
    }
    unit = f"msa-seat-{seat.name}"
    _systemd_run(
        unit,
        [compositor],
        uid=uid,
        env=env,
        properties=[
            "PAMName=login",
            "Restart=on-failure",
            "RestartSec=1s",
            "TimeoutStartSec=20s",
        ],
    )
    wayland_display = _wait_for_wayland(uid, f"{unit}.service")
    _start_user_apps(seat.name, uid, wayland_display)


def _rollback_after_failed_start() -> None:
    stop_transient_units(
        exclude={ACTIVATE_UNIT, RESTORE_UNIT},
        include_legacy=False,
    )
    flush_inputs()
    _run(["systemctl", "isolate", "graphical.target"], check=False, timeout=30)


def activate_now(config: Config) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")

    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    missing = [check.message for check in doctor(config) if not check.ok]
    if missing:
        raise RuntimeError("Pré-validação falhou: " + ", ".join(missing))

    try:
        stop_transient_units(
            exclude={ACTIVATE_UNIT, RESTORE_UNIT},
            include_legacy=True,
        )

        _run(
            ["systemctl", "isolate", "multi-user.target"],
            timeout=30,
        )
        time.sleep(0.4)

        flush_inputs()
        attach_inputs(config)

        dlm = _resolve_binary(
            "drm-lease-manager",
            "/usr/local/bin/drm-lease-manager",
        )
        if not dlm:
            raise RuntimeError("drm-lease-manager não encontrado.")

        cards = sorted({seat.connector.split("-", 1)[0] for seat in config.seats})
        for card in cards:
            _systemd_run(
                f"msa-dlm-{card}",
                [dlm, f"/dev/dri/{card}"],
                properties=[
                    "Restart=on-failure",
                    "RestartSec=1s",
                ],
            )

        for index in range(len(config.seats)):
            _start_seat(config, index)
    except Exception:
        _rollback_after_failed_start()
        raise


def _helper_binary() -> str:
    binary = _resolve_binary("multi-seat-arch")
    if not binary:
        raise RuntimeError("Executável multi-seat-arch não encontrado no PATH.")
    return binary


def _schedule_helper(unit: str, command: str) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed", unit], check=False)
    _systemd_run(
        unit.removesuffix(".service"),
        [_helper_binary(), command],
        properties=[
            "IgnoreOnIsolate=yes",
            "TimeoutStartSec=120s",
        ],
        no_block=True,
    )


def start(config: Config) -> None:
    """Schedule activation in a detached root service."""

    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    _schedule_helper(ACTIVATE_UNIT, "_activate")


def restore_now() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    stop_transient_units(
        exclude={ACTIVATE_UNIT, RESTORE_UNIT},
        include_legacy=True,
    )
    flush_inputs()
    _run(["systemctl", "isolate", "graphical.target"], check=False, timeout=30)


def restore() -> None:
    _schedule_helper(RESTORE_UNIT, "_restore-now")
