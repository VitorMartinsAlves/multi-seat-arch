from __future__ import annotations

import shutil
import time
from types import ModuleType

from .dynamic_login import enabled as dynamic_login_enabled

LOGIN_MANAGER_UNIT = "msa-app-login-manager"
LOGIN_MANAGER_SERVICE = LOGIN_MANAGER_UNIT + ".service"


def _wait_for_greeters(backend: ModuleType, config, timeout: float = 15.0) -> None:
    """Refuse to leave the machine on leased black screens without a greeter."""
    expected = max(1, len(backend.active_seats(config)))
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        if backend._unit_failed(LOGIN_MANAGER_SERVICE):
            log = backend._unit_log_tail(LOGIN_MANAGER_SERVICE, lines=120)
            raise RuntimeError(
                "Atrium encerrou antes de abrir as telas de login."
                + (f"\n{log}" if log else "")
            )

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
            if len(greeters) >= expected:
                return

        time.sleep(0.2)

    log = backend._unit_log_tail(LOGIN_MANAGER_SERVICE, lines=160)
    raise RuntimeError(
        f"Atrium ficou ativo, mas não abriu os {expected} greeter(s) esperados em {timeout:.0f}s."
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

        # Reuse the activation path for DRM leases, synthetic logind seats and
        # input routing, but suppress the legacy fixed-user compositor launch.
        original_start_seat = backend._start_seat

        def skip_fixed_user_seat(_config, _seat) -> None:
            return None

        backend._start_seat = skip_fixed_user_seat
        try:
            previous_activate(config)
        finally:
            backend._start_seat = original_start_seat

        try:
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
            # A running DRM lease with no greeter produces a permanent black
            # screen. Treat that as activation failure and immediately return
            # the machine to its normal graphical target.
            backend._persist_activation_error(exc)
            backend._run(["systemctl", "stop", LOGIN_MANAGER_SERVICE], check=False)
            backend._rollback_after_failed_start()
            raise

    backend.activate_now = activate
    backend._msa_runtime_patch_v7_installed = True
