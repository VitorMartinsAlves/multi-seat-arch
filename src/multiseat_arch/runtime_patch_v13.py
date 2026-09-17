from __future__ import annotations

import time
from pathlib import Path
from types import ModuleType

from . import audio_seat


def _restart_display_manager(backend: ModuleType) -> None:
    """Bring the normal host login/desktop back without killing our helper."""
    backend._run(["systemctl", "start", "graphical.target"], check=False, timeout=30)

    # display-manager.service is normally an alias to SDDM on CachyOS/KDE.
    # Restart it explicitly because multiseat activation stopped it to release
    # DRM master. Merely starting an already-active graphical.target does not
    # necessarily start the display manager again.
    result = backend._run(
        ["systemctl", "restart", "display-manager.service"],
        check=False,
        timeout=30,
    )
    if result.returncode != 0:
        backend._run(["systemctl", "restart", "sddm.service"], check=False, timeout=30)

    deadline = time.monotonic() + 12.0
    while time.monotonic() < deadline:
        active = backend._run(
            ["systemctl", "is-active", "--quiet", "display-manager.service"],
            check=False,
            timeout=3,
        )
        if active.returncode == 0:
            return
        active = backend._run(
            ["systemctl", "is-active", "--quiet", "sddm.service"],
            check=False,
            timeout=3,
        )
        if active.returncode == 0:
            return
        time.sleep(0.25)

    # One last non-fatal retry. The GUI/helper must still be allowed to finish
    # and clean up even if the host display manager itself has another problem.
    backend._run(["systemctl", "start", "sddm.service"], check=False, timeout=30)


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v13_installed", False):
        return

    def restore_now() -> None:
        if backend.os.geteuid() != 0:
            raise PermissionError("Execute como root.")

        # Do not `isolate graphical.target` from msa-restore.service. isolate can
        # terminate the transient restore helper itself before recovery finishes,
        # leaving both displays black. Stop only the multiseat units, restore
        # device ownership, then explicitly restart the normal display manager.
        backend._run(["systemctl", "stop", backend.ACTIVATE_UNIT], check=False)
        backend.stop_transient_units(
            exclude={backend.RESTORE_UNIT},
            include_legacy=True,
        )

        backend.flush_inputs()

        # Restore physical audio hardware to the normal host topology as part of
        # the same transaction. Also remove the legacy runtime rule if present.
        try:
            audio_seat.clear_runtime_audio_seats(backend)
        except Exception:
            pass
        for legacy in (
            Path("/run/udev/rules.d/99-multi-seat-arch-runtime-audio.rules"),
            Path("/run/udev/rules.d/74-multi-seat-arch-runtime-audio.rules"),
        ):
            try:
                legacy.unlink(missing_ok=True)
            except OSError:
                pass
        backend._run(["udevadm", "control", "--reload"], check=False)
        backend._run(
            ["udevadm", "trigger", "--subsystem-match=sound", "--action=change"],
            check=False,
        )
        backend._run(["udevadm", "settle", "--timeout=5"], check=False)

        _restart_display_manager(backend)

    backend.restore_now = restore_now
    backend._msa_runtime_patch_v13_installed = True
