from __future__ import annotations

import pwd
import shutil
from pathlib import Path
from types import ModuleType

from .runtime_patch import _seat_service_properties

PLASMA_COMPOSITOR = "kwin-wayland-msa"


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

        # Let KWin's own wrapper allocate the Wayland socket. Forcing --socket
        # on kwin_wayland_wrapper caused both compositors to come up black on
        # the target CachyOS/KWin 6.7.5 host. The users are distinct, so their
        # XDG_RUNTIME_DIR namespaces are already isolated; we only need to bind
        # Plasma to the exact socket that this compositor actually created.
        wayland_display = backend._wait_for_wayland(uid, f"{unit}.service", timeout=25.0)

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
