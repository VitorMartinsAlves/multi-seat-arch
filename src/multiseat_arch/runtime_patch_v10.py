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
    error_path = str(backend.LAST_ERROR)
    message = (
        "Activation watchdog timeout: multiseat did not confirm greeters within "
        f"{WATCHDOG_SECONDS}s; forced recovery executed."
    )

    # Recovery intentionally does not call the project CLI. It must still work
    # if Python/imports/the activation helper itself are the thing that failed.
    # Stop every transient MSA component, return inputs to seat0 and explicitly
    # restart the host display manager. Merely isolating graphical.target is not
    # enough when graphical.target remained active while display-manager.service
    # was stopped during activation.
    shell = " ; ".join(
        [
            f"mkdir -p {shlex.quote(str(backend.LAST_ERROR.parent))}",
            f"printf '%s\\n' {shlex.quote(message)} > {shlex.quote(error_path)}",
            "systemctl stop msa-app-login-manager.service 'msa-app-*' 'msa-seat-*' 'msa-input-*' 'msa-dlm-*' msa-hotplug.service 2>/dev/null || true",
            f"rm -f {shlex.quote(str(backend.RUNTIME_UDEV_RULES))}",
            "loginctl flush-devices 2>/dev/null || true",
            "udevadm control --reload 2>/dev/null || true",
            "udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true",
            "udevadm settle --timeout=5 2>/dev/null || true",
            "systemctl reset-failed display-manager.service 2>/dev/null || true",
            "systemctl start graphical.target 2>/dev/null || true",
            "systemctl restart display-manager.service 2>/dev/null || systemctl restart sddm.service 2>/dev/null || true",
        ]
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

    previous_start = backend.start
    previous_activate = backend.activate_now

    def start(config) -> None:
        # This runs synchronously from the privileged CLI while the normal
        # desktop still exists. Arm recovery BEFORE msa-activate.service is even
        # scheduled, so a failure to start that service cannot strand the host.
        _arm(backend)
        try:
            previous_start(config)
        except BaseException:
            _disarm(backend)
            raise

    def activate(config) -> None:
        try:
            previous_activate(config)
        except BaseException:
            # Keep the timer armed. Inner rollback may recover immediately; if
            # it does not, this independent timer is the final safety net.
            raise
        else:
            # In dynamic-login mode all inner wrappers have returned only after
            # the expected greeters were observed.
            _disarm(backend)

    backend.start = start
    backend.activate_now = activate
    backend._msa_runtime_patch_v10_installed = True
