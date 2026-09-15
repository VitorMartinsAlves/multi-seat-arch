from __future__ import annotations

import pwd
import shutil
import socket
import time
from pathlib import Path
from types import ModuleType

from .runtime_patch import _seat_service_properties

PLASMA_COMPOSITOR = "kwin-wayland-msa"


def _socket_name(seat_name: str) -> str:
    """Return a deterministic Wayland socket name for one logical seat."""
    return f"wayland-msa-{seat_name}"


def _wait_for_exact_wayland_socket(
    backend: ModuleType,
    uid: int,
    socket_name: str,
    unit: str,
    timeout: float = 25.0,
) -> str:
    """Wait for the exact socket created for this KWin instance.

    The generic backend waiter scans every wayland-* entry in XDG_RUNTIME_DIR.
    That is fine for a single compositor, but a user manager may retain stale
    sockets/environment from an older session. Plasma then gets pointed at the
    wrong socket and repeatedly fails with "Failed to create wl_display".
    """
    path = Path(f"/run/user/{uid}") / socket_name
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.settimeout(0.25)
            try:
                probe.connect(str(path))
            except OSError:
                pass
            else:
                probe.close()
                return socket_name
            finally:
                try:
                    probe.close()
                except OSError:
                    pass

        if not backend._unit_active(unit):
            journal = backend._run(
                ["journalctl", "-u", unit, "--no-pager", "-n", "100"],
                check=False,
            ).stdout
            raise RuntimeError(
                f"KWin encerrou antes de criar {socket_name}.\n{journal[-12000:]}"
            )
        time.sleep(0.1)

    raise RuntimeError(
        f"KWin não criou o socket Wayland esperado {path} em {timeout:.0f}s."
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
        wayland_display = _socket_name(seat.name)

        # A compositor killed during an earlier experiment can leave socket and
        # lock files behind. They are safe to remove here because the matching
        # transient unit is stopped before activation starts.
        for stale in (
            runtime_dir / wayland_display,
            runtime_dir / f"{wayland_display}.lock",
        ):
            try:
                stale.unlink(missing_ok=True)
            except OSError:
                pass

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
            [compositor, "--no-lockscreen", "--socket", wayland_display],
            uid=uid,
            env=env,
            properties=_seat_service_properties(),
        )
        _wait_for_exact_wayland_socket(
            backend,
            uid,
            wayland_display,
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
