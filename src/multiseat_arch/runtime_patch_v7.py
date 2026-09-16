from __future__ import annotations

import shutil
from types import ModuleType

from .dynamic_login import enabled as dynamic_login_enabled

LOGIN_MANAGER_UNIT = "msa-app-login-manager"


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

        # Reuse the already proven activation path for DRM-lease-manager,
        # synthetic logind seats and input routing, but suppress the old
        # per-seat fixed-user compositor launches. Atrium takes ownership of
        # session lifecycle after the hardware seats exist.
        original_start_seat = backend._start_seat

        def skip_fixed_user_seat(_config, _seat) -> None:
            return None

        backend._start_seat = skip_fixed_user_seat
        try:
            previous_activate(config)
        finally:
            backend._start_seat = original_start_seat

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

    backend.activate_now = activate
    backend._msa_runtime_patch_v7_installed = True
