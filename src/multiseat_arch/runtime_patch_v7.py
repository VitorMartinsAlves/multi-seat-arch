from __future__ import annotations

import pwd
import shutil
import socket
import time
from pathlib import Path
from types import ModuleType

from .dynamic_login import enabled as dynamic_login_enabled

LOGIN_MANAGER_UNIT = "msa-app-login-manager"
LOGIN_MANAGER_SERVICE = LOGIN_MANAGER_UNIT + ".service"
GREETER_STABLE_SECONDS = 3.0


def _logind_seats(backend: ModuleType) -> set[str]:
    result = backend._run(
        ["loginctl", "list-seats", "--no-legend", "--no-pager"],
        check=False,
    )
    seats: set[str] = set()
    for line in result.stdout.splitlines():
        fields = line.split()
        if fields:
            seats.add(fields[0])
    return seats


def _wait_for_logind_seats(backend: ModuleType, config, timeout: float = 8.0) -> None:
    """Wait until logind publishes every synthetic hardware seat."""
    expected = {
        backend.runtime_seat_name(seat)
        for seat in backend.active_seats(config)
    }
    deadline = time.monotonic() + timeout
    current: set[str] = set()

    while time.monotonic() < deadline:
        current = _logind_seats(backend)
        if expected.issubset(current):
            return
        time.sleep(0.2)

    missing = sorted(expected - current)
    details: list[str] = []
    for seat in missing:
        status = backend._run(
            ["loginctl", "seat-status", seat],
            check=False,
        )
        text = status.stdout.strip()
        if text:
            details.append(f"{seat}: {text}")

    message = (
        "logind não publicou todos os seats do multiseat. "
        f"Esperados: {', '.join(sorted(expected))}. "
        f"Detectados: {', '.join(sorted(current)) or '<nenhum>'}. "
        f"Ausentes: {', '.join(missing) or '<nenhum>'}."
    )
    if details:
        message += "\n" + "\n".join(details)
    raise RuntimeError(message)


def _runtime_dir_for_seat(runtime_seat: str) -> Path:
    account = pwd.getpwnam("atriumdm")
    safe_seat = "".join(
        ch if ch.isalnum() or ch in "-_." else "_"
        for ch in runtime_seat
    )
    return Path(f"/run/user/{account.pw_uid}/multi-seat-arch/{safe_seat}")


def _socket_connectable(path: Path) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.2)
    try:
        client.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        client.close()


def _seat_has_wayland(runtime_seat: str) -> bool:
    runtime = _runtime_dir_for_seat(runtime_seat)
    if not runtime.is_dir():
        return False
    for path in sorted(runtime.glob("wayland-*")):
        if path.name.endswith(".lock"):
            continue
        try:
            if path.is_socket() and _socket_connectable(path):
                return True
        except OSError:
            continue
    return False


def _wait_for_greeters(backend: ModuleType, config, timeout: float = 25.0) -> None:
    """Require a stable, independently connectable Wayland compositor per seat."""
    runtime_seats = [
        backend.runtime_seat_name(seat)
        for seat in backend.active_seats(config)
    ]
    expected = max(1, len(runtime_seats))
    deadline = time.monotonic() + timeout
    stable_since: float | None = None

    while time.monotonic() < deadline:
        if backend._unit_failed(LOGIN_MANAGER_SERVICE):
            log = backend._unit_log_tail(LOGIN_MANAGER_SERVICE, lines=160)
            raise RuntimeError(
                "Atrium encerrou antes de abrir as telas de login."
                + (f"\n{log}" if log else "")
            )

        healthy = False
        if backend._unit_active(LOGIN_MANAGER_SERVICE):
            processes = backend._run(
                [
                    "pgrep",
                    "-fa",
                    "multi-seat-arch-login-greeter|atrium-gtk-greeter",
                ],
                check=False,
            )
            greeters = [line for line in processes.stdout.splitlines() if line.strip()]
            sockets_ready = all(_seat_has_wayland(seat) for seat in runtime_seats)
            healthy = len(greeters) >= expected and sockets_ready

        if healthy:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= GREETER_STABLE_SECONDS:
                return
        else:
            stable_since = None

        time.sleep(0.2)

    log = backend._unit_log_tail(LOGIN_MANAGER_SERVICE, lines=220)
    states = ", ".join(
        f"{seat}={'wayland-ok' if _seat_has_wayland(seat) else 'sem-wayland'}"
        for seat in runtime_seats
    )
    raise RuntimeError(
        f"Atrium não estabilizou os {expected} greeter(s) em {timeout:.0f}s. "
        f"Estado: {states}."
        + (f"\n{log}" if log else "")
    )


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v7_installed", False):
        return

    previous_activate = backend.activate_now

    def activate(config) -> None:
        if not dynamic_login_enabled():
            previous_activate(config)
            return

        atrium = shutil.which("atrium")
        if not atrium:
            raise RuntimeError(
                "Modo de login dinâmico está ativo, mas Atrium não foi encontrado. "
                "Rode scripts/build-atrium-login-manager.sh."
            )

        original_start_seat = backend._start_seat

        def skip_fixed_user_seat(_config, _seat) -> None:
            return None

        backend._start_seat = skip_fixed_user_seat
        try:
            previous_activate(config)
        finally:
            backend._start_seat = original_start_seat

        try:
            _wait_for_logind_seats(backend, config)

            backend._systemd_run(
                LOGIN_MANAGER_UNIT,
                [atrium],
                properties=[
                    "Restart=on-failure",
                    "RestartSec=2s",
                    "IgnoreOnIsolate=yes",
                    "TimeoutStartSec=20s",
                ],
                no_block=True,
            )
            _wait_for_greeters(backend, config)
        except Exception as exc:
            backend._persist_activation_error(exc)
            backend._run(["systemctl", "stop", LOGIN_MANAGER_SERVICE], check=False)
            backend._rollback_after_failed_start()
            raise

    backend.activate_now = activate
    backend._msa_runtime_patch_v7_installed = True
