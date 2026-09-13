from __future__ import annotations

import importlib.util
import os
import pwd
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .discovery import connector_lease_name, discover_inputs
from .model import Config, DeviceRule, InputDevice, Seat

ACTIVATE_UNIT = "msa-activate.service"
RESTORE_UNIT = "msa-restore.service"
HOTPLUG_UNIT = "msa-hotplug.service"
UNIT_PREFIXES = (
    "msa-seat-",
    "msa-app-",
    "msa-input-",
    "msa-dlm-",
    "msa-hotplug",
)
LEGACY_UNIT_PREFIXES = ("multiseat-card", "dlm-card")
READY_DIR = Path("/run/multi-seat-arch/input")


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


def _needs_proxy(config: Config | None) -> bool:
    return bool(
        config
        and any(rule.mode in {"shared", "disabled"} for rule in config.devices)
    )


def doctor(config: Config | None = None) -> list[Check]:
    checks = [
        Check(command_exists("systemctl"), "systemctl"),
        Check(command_exists("systemd-run"), "systemd-run"),
        Check(command_exists("loginctl"), "systemd-logind/loginctl"),
        Check(command_exists("udevadm"), "udevadm"),
        Check(command_exists("localectl"), "localectl"),
        Check(command_exists("journalctl"), "journalctl"),
        Check(command_exists("ldd"), "ldd"),
    ]

    if _needs_proxy(config):
        checks.extend(
            [
                Check(importlib.util.find_spec("evdev") is not None, "python-evdev"),
                Check(Path("/dev/uinput").exists(), "/dev/uinput"),
            ]
        )

    dlm = _resolve_binary(
        "drm-lease-manager", "/usr/local/bin/drm-lease-manager"
    )
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
        legacy = (
            _run(
                ["systemctl", "is-active", "--quiet", "multiseat.service"],
                check=False,
            ).returncode
            == 0
        )
        checks.append(
            Check(
                not legacy,
                "serviço legado multiseat.service não está ativo"
                if not legacy
                else "serviço legado multiseat.service está ativo",
            )
        )
    return checks


def active_seats(config: Config) -> list[Seat]:
    return [seat for seat in config.seats if seat.enabled]


def _seat_has_configured_input(config: Config, seat: Seat) -> bool:
    if seat.inputs:
        return True
    if any(rule.mode == "shared" for rule in config.devices):
        return True
    return any(
        rule.mode == "seat" and rule.seat == seat.name
        for rule in config.devices
    )


def validate(config: Config) -> list[str]:
    errors: list[str] = []
    if config.version != 2:
        errors.append(f"Versão de configuração não suportada: {config.version}")

    seats = active_seats(config)
    if not seats:
        errors.append("Habilite pelo menos um seat.")

    connectors: set[str] = set()
    names: set[str] = set()
    users: set[str] = set()
    all_names = {seat.name for seat in config.seats}

    for seat in config.seats:
        if not re.fullmatch(r"seat-[A-Za-z0-9_-]+", seat.name):
            errors.append(f"Nome de seat inválido: {seat.name}")
        if seat.name in names:
            errors.append(f"Seat duplicado: {seat.name}")
        names.add(seat.name)

        if not seat.enabled:
            continue

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

        for syspath in seat.inputs:
            if not syspath.startswith("/sys/devices/"):
                errors.append(f"Syspath legado de input inválido: {syspath}")

    keys: set[str] = set()
    for rule in config.devices:
        if not rule.key or not re.fullmatch(r"input-[a-f0-9]{24}", rule.key):
            errors.append(
                f"Chave de periférico inválida: {rule.key or '<vazia>'}"
            )
        if rule.key in keys:
            errors.append(f"Regra duplicada de periférico: {rule.key}")
        keys.add(rule.key)
        if rule.mode == "seat":
            if not rule.seat:
                errors.append(
                    f"Periférico {rule.name or rule.key} não tem seat definido."
                )
            elif rule.seat not in all_names:
                errors.append(
                    f"Seat inexistente na regra de {rule.name or rule.key}: "
                    f"{rule.seat}"
                )
            else:
                target = next(
                    seat for seat in config.seats if seat.name == rule.seat
                )
                if not target.enabled:
                    errors.append(
                        f"Periférico {rule.name or rule.key} aponta para seat "
                        "desabilitado."
                    )
        elif rule.seat:
            errors.append(
                f"Regra {rule.name or rule.key} em modo {rule.mode} não deve "
                "definir seat."
            )

    for seat in seats:
        if not _seat_has_configured_input(config, seat):
            errors.append(
                f"{seat.name} não possui nenhum input atribuído ou compartilhado."
            )

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


def _wait_assignments(
    assignments: list[tuple[str, str]], timeout: float = 5.0
) -> None:
    deadline = time.monotonic() + timeout
    pending = set(assignments)
    while pending and time.monotonic() < deadline:
        pending = {
            (seat, syspath)
            for seat, syspath in pending
            if _udev_seat(syspath) != seat
        }
        if pending:
            time.sleep(0.1)
    if pending:
        detail = ", ".join(
            f"{path} -> {seat}" for seat, path in sorted(pending)
        )
        raise RuntimeError("Falha ao atribuir inputs: " + detail)


def _attach(seat: str, syspath: str) -> None:
    _run(["loginctl", "attach", seat, syspath])


def _list_units(prefixes: tuple[str, ...]) -> list[str]:
    out = _run(
        ["systemctl", "list-units", "--all", "--plain", "--no-legend"],
        check=False,
    ).stdout
    units: list[str] = []
    for line in out.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if unit and unit.startswith(prefixes):
            units.append(unit)
    return units


def _stop_units(prefixes: tuple[str, ...]) -> None:
    for unit in _list_units(prefixes):
        _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed"], check=False)


def stop_transient_units(
    *,
    exclude: set[str] | None = None,
    include_legacy: bool = True,
) -> None:
    exclude = exclude or set()
    prefixes = UNIT_PREFIXES + (
        LEGACY_UNIT_PREFIXES if include_legacy else ()
    )
    units = [
        unit for unit in _list_units(prefixes) if unit not in exclude
    ]
    units.sort(key=lambda unit: unit.startswith("msa-dlm-"))
    for unit in units:
        _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed"], check=False)
    _run(["systemctl", "daemon-reload"], check=False)


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


def _proxy_unit(key: str) -> str:
    return f"msa-input-{key.removeprefix('input-')}"


def _ready_file(key: str) -> Path:
    return READY_DIR / f"{key}.json"


def _unit_active(unit: str) -> bool:
    return (
        _run(
            ["systemctl", "is-active", "--quiet", unit], check=False
        ).returncode
        == 0
    )


def _unit_failed(unit: str) -> bool:
    return (
        _run(
            ["systemctl", "is-failed", "--quiet", unit], check=False
        ).returncode
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


def _wait_proxy(key: str, unit: str, timeout: float = 6.0) -> None:
    ready = _ready_file(key)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if ready.exists():
            return
        if _unit_failed(f"{unit}.service"):
            log = _unit_log_tail(f"{unit}.service")
            raise RuntimeError(
                f"Proxy de input falhou para {key}."
                + (f"\n{log}" if log else "")
            )
        time.sleep(0.1)
    raise RuntimeError(f"Proxy de input não ficou pronto: {key}")


def _start_proxy(
    device: InputDevice, rule: DeviceRule, config: Config
) -> None:
    unit = _proxy_unit(rule.key)
    ready = _ready_file(rule.key)
    ready.parent.mkdir(parents=True, exist_ok=True)
    ready.unlink(missing_ok=True)

    command = [
        sys.executable,
        "-m",
        "multiseat_arch.input_proxy",
        "--source",
        device.event,
        "--ready",
        str(ready),
    ]
    if rule.mode == "shared":
        for seat in active_seats(config):
            command.extend(["--seat", seat.name])

    _systemd_run(
        unit,
        command,
        properties=[
            "Restart=on-failure",
            "RestartSec=2s",
            "TimeoutStartSec=10s",
            "KillMode=control-group",
        ],
        no_block=True,
    )
    _wait_proxy(rule.key, unit)


def resolve_device_rules(
    config: Config,
) -> list[tuple[DeviceRule, InputDevice]]:
    by_key = {
        device.key: device for device in discover_inputs() if device.key
    }
    return [
        (rule, by_key[rule.key])
        for rule in config.devices
        if rule.mode != "unmanaged" and rule.key in by_key
    ]


def sync_devices_now(config: Config) -> None:
    """Apply peripheral routing; caller serializes concurrent live changes."""
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))

    _stop_units(("msa-input-",))
    READY_DIR.mkdir(parents=True, exist_ok=True)
    for path in READY_DIR.glob("*.json"):
        path.unlink(missing_ok=True)

    flush_inputs()
    assignments: list[tuple[str, str]] = []

    # v1 compatibility/migration path.
    for seat in active_seats(config):
        for syspath in seat.inputs:
            if Path(syspath).exists():
                _attach(seat.name, syspath)
                assignments.append((seat.name, syspath))

    for rule, device in resolve_device_rules(config):
        if rule.mode == "seat":
            _attach(rule.seat, device.syspath)
            assignments.append((rule.seat, device.syspath))
        elif rule.mode in {"shared", "disabled"}:
            _start_proxy(device, rule, config)

    _run(["udevadm", "settle", "--timeout=5"], check=False)
    if assignments:
        _wait_assignments(assignments)


def _lease_runtime_dirs() -> list[Path]:
    return [
        Path("/var/local/run/drm-lease-manager"),
        Path("/var/run/drm-lease-manager"),
    ]


def _wait_for_lease(
    lease: str, uid: int, timeout: float = 15.0
) -> None:
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


def _wait_for_wayland(
    uid: int, unit: str, timeout: float = 12.0
) -> str:
    runtime = Path(f"/run/user/{uid}")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        sockets = [
            path
            for path in sorted(runtime.glob("wayland-*"))
            if not path.name.endswith(".lock")
            and path.is_socket()
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


def _start_user_apps(
    seat_name: str, uid: int, wayland_display: str
) -> None:
    env = {
        "XDG_SESSION_TYPE": "wayland",
        "XDG_CURRENT_DESKTOP": "labwc",
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "XDG_SEAT": seat_name,
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


def _start_seat(config: Config, seat: Seat) -> None:
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
        "XDG_RUNTIME_DIR": f"/run/user/{uid}",
        "SEATD_VTBOUND": "0",
        "XKB_DEFAULT_LAYOUT": _keyboard_layout(),
        # Allow startup when a configured Bluetooth/USB input is temporarily
        # disconnected. libinput keeps watching this seat for later hotplug.
        "WLR_LIBINPUT_NO_DEVICES": "1",
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


def _helper_binary() -> str:
    binary = _resolve_binary("multi-seat-arch")
    if not binary:
        raise RuntimeError(
            "Executável multi-seat-arch não encontrado no PATH."
        )
    return binary


def _start_hotplug_watcher() -> None:
    _run(["systemctl", "stop", HOTPLUG_UNIT], check=False)
    _systemd_run(
        HOTPLUG_UNIT.removesuffix(".service"),
        [_helper_binary(), "_watch-inputs"],
        properties=[
            "Restart=always",
            "RestartSec=2s",
            "IgnoreOnIsolate=yes",
        ],
        no_block=True,
    )


def _rollback_after_failed_start() -> None:
    stop_transient_units(
        exclude={ACTIVATE_UNIT, RESTORE_UNIT}, include_legacy=False
    )
    flush_inputs()
    _run(
        ["systemctl", "isolate", "graphical.target"],
        check=False,
        timeout=30,
    )


def activate_now(config: Config) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    # If a previous restore helper is still around, this explicit activation
    # supersedes it. CLI also performs this step before scheduling us.
    _run(["systemctl", "stop", RESTORE_UNIT], check=False)

    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    missing = [check.message for check in doctor(config) if not check.ok]
    if missing:
        raise RuntimeError("Pré-validação falhou: " + ", ".join(missing))

    try:
        stop_transient_units(
            exclude={ACTIVATE_UNIT, RESTORE_UNIT}, include_legacy=True
        )
        _run(["systemctl", "isolate", "multi-user.target"], timeout=30)
        time.sleep(0.4)

        dlm = _resolve_binary(
            "drm-lease-manager", "/usr/local/bin/drm-lease-manager"
        )
        if not dlm:
            raise RuntimeError("drm-lease-manager não encontrado.")

        seats = active_seats(config)
        cards = sorted(
            {seat.connector.split("-", 1)[0] for seat in seats}
        )
        for card in cards:
            _systemd_run(
                f"msa-dlm-{card}",
                [dlm, f"/dev/dri/{card}"],
                properties=["Restart=on-failure", "RestartSec=1s"],
            )

        sync_devices_now(config)
        for seat in seats:
            _start_seat(config, seat)
        _start_hotplug_watcher()
    except Exception:
        _rollback_after_failed_start()
        raise


def _schedule_helper(unit: str, command: str) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    _run(["systemctl", "stop", unit], check=False)
    _run(["systemctl", "reset-failed", unit], check=False)
    _systemd_run(
        unit.removesuffix(".service"),
        [_helper_binary(), command],
        properties=["IgnoreOnIsolate=yes", "TimeoutStartSec=180s"],
        no_block=True,
    )


def start(config: Config) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    errors = validate(config)
    if errors:
        raise RuntimeError("\n".join(errors))
    _schedule_helper(ACTIVATE_UNIT, "_activate")


def restore_now() -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    # Recovery wins over activation even when called directly, outside the CLI.
    _run(["systemctl", "stop", ACTIVATE_UNIT], check=False)
    stop_transient_units(
        exclude={RESTORE_UNIT}, include_legacy=True
    )
    flush_inputs()
    _run(
        ["systemctl", "isolate", "graphical.target"],
        check=False,
        timeout=30,
    )


def restore() -> None:
    _schedule_helper(RESTORE_UNIT, "_restore-now")
