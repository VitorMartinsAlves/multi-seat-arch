from __future__ import annotations

import pwd
import shutil
import socket
import time
from pathlib import Path
from types import ModuleType

from .runtime_patch import _seat_service_properties

PLASMA_COMPOSITOR = "kwin-wayland-msa"


def _wayland_socket_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_socket():
        return None
    return (stat.st_ino, stat.st_mtime_ns)


def _snapshot_wayland_sockets(runtime_dir: Path, uid: int) -> dict[str, tuple[int, int]]:
    snapshot: dict[str, tuple[int, int]] = {}
    for path in runtime_dir.glob("wayland-*"):
        if path.name.endswith(".lock"):
            continue
        try:
            if path.stat().st_uid != uid:
                continue
        except OSError:
            continue
        fingerprint = _wayland_socket_fingerprint(path)
        if fingerprint is not None:
            snapshot[path.name] = fingerprint
    return snapshot


def _socket_accepts_connections(path: Path) -> bool:
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.2)
    try:
        probe.connect(str(path))
    except OSError:
        return False
    finally:
        probe.close()
    return True


def _wait_for_new_wayland_socket(
    backend: ModuleType,
    uid: int,
    runtime_dir: Path,
    before: dict[str, tuple[int, int]],
    unit: str,
    timeout: float = 25.0,
) -> str:
    """Return the socket created by this KWin instance, never a stale one.

    The generic backend waiter returns the first ``wayland-*`` socket in the
    user's runtime directory. On the secondary Plasma user that directory can
    contain a stale socket from an earlier failed attempt, so plasmashell gets
    pointed at a dead compositor while KWin itself is actually running.

    Compare inode/mtime against a pre-launch snapshot and require that the
    selected socket accepts a real AF_UNIX connection. This also handles KWin
    reusing the same name after replacing a stale socket because the inode will
    change.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        candidates: list[Path] = []
        for path in sorted(runtime_dir.glob("wayland-*")):
            if path.name.endswith(".lock"):
                continue
            try:
                if path.stat().st_uid != uid:
                    continue
            except OSError:
                continue
            current = _wayland_socket_fingerprint(path)
            if current is None:
                continue
            if before.get(path.name) == current:
                continue
            candidates.append(path)

        for path in candidates:
            if _socket_accepts_connections(path):
                return path.name

        if backend._unit_failed(unit) or not backend._unit_active(unit):
            log = backend._unit_log_tail(unit, lines=120)
            raise RuntimeError(
                f"KWin encerrou antes de publicar um socket Wayland novo ({unit})."
                + (f"\n{log}" if log else "")
            )
        time.sleep(0.1)

    existing = ", ".join(sorted(_snapshot_wayland_sockets(runtime_dir, uid))) or "nenhum"
    log = backend._unit_log_tail(unit, lines=120)
    raise RuntimeError(
        "KWin não publicou um socket Wayland novo e conectável em "
        f"{timeout:.0f}s para uid={uid}. Sockets atuais: {existing}."
        + (f"\n{log}" if log else "")
    )


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v6_installed", False):
        return

    previous_start_seat = backend._start_seat

    def start_seat(config, seat) -> None:
        compositor_name = Path(config.compositor).name
        if compositor_name != PLASMA_COMPOSITOR:
            previous_start_seat(config, seat)
            return

        account = pwd.getpwnam(seat.user)
        uid = account.pw_uid
        runtime = backend.runtime_seat_name(seat)
        backend._wait_for_lease(seat.connector, uid)

        compositor = (
            config.compositor
            if Path(config.compositor).is_file()
            else backend._resolve_binary(compositor_name)
        )
        if not compositor:
            raise RuntimeError(
                "KWin experimental não encontrado. Rode scripts/build-kwin-plasma.sh."
            )

        helper = shutil.which("multi-seat-arch-plasma-session")
        if not helper:
            raise RuntimeError("multi-seat-arch-plasma-session não encontrado; reinstale o pacote.")

        card = seat.connector.split("-", 1)[0]
        runtime_dir = Path(f"/run/user/{uid}")
        runtime_dir.mkdir(parents=True, exist_ok=True)
        sockets_before = _snapshot_wayland_sockets(runtime_dir, uid)

        env = {
            "XDG_SEAT": runtime,
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": "KDE",
            "XDG_SESSION_DESKTOP": "KDE",
            "XDG_RUNTIME_DIR": str(runtime_dir),
            "DBUS_SESSION_BUS_ADDRESS": f"unix:path={runtime_dir}/bus",
            "KDE_FULL_SESSION": "true",
            "KDE_SESSION_VERSION": "6",
            "KWIN_DRM_LEASE": seat.connector,
            "KWIN_DRM_DEVICES": f"/dev/dri/{card}",
            "QT_QPA_PLATFORM": "wayland;xcb",
            "MOZ_ENABLE_WAYLAND": "1",
        }

        unit = f"msa-seat-{seat.name}"
        backend._systemd_run(
            unit,
            [compositor, "--no-lockscreen"],
            uid=uid,
            env=env,
            properties=_seat_service_properties(),
        )

        # kwin_wayland_wrapper must choose the socket itself because it creates
        # and passes the listening FD to kwin_wayland. We identify the exact
        # socket created by this launch rather than taking the first stale
        # wayland-* entry from XDG_RUNTIME_DIR.
        wayland_display = _wait_for_new_wayland_socket(
            backend,
            uid,
            runtime_dir,
            sockets_before,
            f"{unit}.service",
            timeout=25.0,
        )

        session_env = dict(env)
        session_env.pop("KWIN_DRM_LEASE", None)
        session_env.pop("KWIN_DRM_DEVICES", None)
        session_env["WAYLAND_DISPLAY"] = wayland_display
        session_env["MSA_WAYLAND_DISPLAY"] = wayland_display

        backend._systemd_run(
            f"msa-app-{seat.name}-plasma",
            [helper],
            uid=uid,
            env=session_env,
            properties=[
                f"After={unit}.service",
                f"PartOf={unit}.service",
                "CapabilityBoundingSet=",
                "AmbientCapabilities=",
                "RestrictNamespaces=no",
                "PrivateUsers=no",
                "NoNewPrivileges=no",
                "Restart=on-failure",
                "RestartSec=2s",
                "StartLimitBurst=3",
                "StartLimitIntervalSec=30s",
            ],
            no_block=True,
        )

    backend._start_seat = start_seat
    backend._msa_runtime_patch_v6_installed = True
