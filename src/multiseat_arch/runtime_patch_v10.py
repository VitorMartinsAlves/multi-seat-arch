from __future__ import annotations

import shlex
from types import ModuleType

WATCHDOG_UNIT = "msa-activation-watchdog"
WATCHDOG_TIMER = WATCHDOG_UNIT + ".timer"
WATCHDOG_SERVICE = WATCHDOG_UNIT + ".service"
WATCHDOG_SECONDS = 45


def _disarm(backend: ModuleType) -> None:
    backend._run(
        ["systemctl", "stop", WATCHDOG_TIMER, WATCHDOG_SERVICE],
        check=False,
    )
    backend._run(
        ["systemctl", "reset-failed", WATCHDOG_TIMER, WATCHDOG_SERVICE],
        check=False,
    )


def _arm(backend: ModuleType) -> None:
    _disarm(backend)
    helper = backend._helper_binary()
    error_path = str(backend.LAST_ERROR)
    message = (
        "Activation watchdog timeout: greeters were not confirmed within "
        f"{WATCHDOG_SECONDS}s; restoring graphical.target automatically."
    )
    shell = (
        f"mkdir -p {shlex.quote(str(backend.LAST_ERROR.parent))}; "
        f"printf '%s\\n' {shlex.quote(message)} > {shlex.quote(error_path)}; "
        f"exec {shlex.quote(helper)} _restore-now"
    )
    backend._run(
        [
            "systemd-run",
            f"--unit={WATCHDOG_UNIT}",
            f"--on-active={WATCHDOG_SECONDS}s",
            "--timer-property=AccuracySec=1s",
            "/bin/sh",
            "-c",
            shell,
        ]
    )


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v10_installed", False):
        return

    previous_activate = backend.activate_now

    def activate(config) -> None:
        # Arm an independent systemd timer before touching the current graphical
        # session. It survives Python crashes, transient-unit failures and input
        # reassignment, so a failed activation cannot strand the host on black
        # screens indefinitely.
        _arm(backend)
        try:
            previous_activate(config)
        except BaseException:
            # Keep the watchdog armed. The normal activation path should roll
            # back immediately; if that rollback is interrupted, the timer is
            # the final recovery path.
            raise
        else:
            # Every inner activation wrapper has returned. In dynamic-login
            # mode this means Atrium is active and the expected greeters were
            # observed, so automatic recovery is no longer needed.
            _disarm(backend)

    backend.activate_now = activate
    backend._msa_runtime_patch_v10_installed = True
