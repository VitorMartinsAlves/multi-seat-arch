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

    audio_rules = getattr(
        backend,
        "RUNTIME_AUDIO_UDEV_RULES",
        "/run/udev/rules.d/74-multi-seat-arch-runtime-audio.rules",
    )

    shell = " ; ".join(
        [
            f"mkdir -p {shlex.quote(str(backend.LAST_ERROR.parent))}",
            f"printf '%s\\n' {shlex.quote(message)} > {shlex.quote(error_path)}",
            "systemctl stop msa-app-login-manager.service 'msa-app-*' 'msa-seat-*' 'msa-input-*' 'msa-dlm-*' msa-hotplug.service 2>/dev/null || true",
            f"rm -f {shlex.quote(str(backend.RUNTIME_UDEV_RULES))} {shlex.quote(str(audio_rules))}",
            "loginctl flush-devices 2>/dev/null || true",
            "udevadm control --reload 2>/dev/null || true",
            "udevadm trigger --subsystem-match=input --action=change 2>/dev/null || true",
            "udevadm trigger --subsystem-match=sound --action=change 2>/dev/null || true",
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
            raise
        else:
            _disarm(backend)

    backend.start = start
    backend.activate_now = activate
    backend._msa_runtime_patch_v10_installed = True
