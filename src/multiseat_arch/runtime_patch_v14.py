from __future__ import annotations

import time
from pathlib import Path
from types import ModuleType

from . import audio_seat
from .runtime_patch_v13 import _restart_display_manager


def _multiseat_users(backend: ModuleType) -> list[str]:
    """Return users currently logged into MSA runtime seats.

    Custom Plasma sessions import seat-specific Wayland/X11 variables into the
    per-user systemd manager. If that user manager survives the transition back
    to SDDM, the next normal Plasma login can inherit a dead WAYLAND_DISPLAY /
    DISPLAY and start as a black desktop. Capture the affected users before the
    transient seat units disappear so restore can reset their user managers.
    """
    result = backend._run(
        ["loginctl", "list-sessions", "--no-legend", "--no-pager"],
        check=False,
        timeout=8,
    )
    users: set[str] = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        # Current runtime_seat_name() produces values such as
        # seat-card1-HDMI-A-1 and seat-card1-eDP-1.
        seat = parts[3]
        if seat.startswith("seat-card"):
            users.add(parts[2])
    return sorted(users)


def _reset_multiseat_users(backend: ModuleType, users: list[str]) -> None:
    """Terminate stale custom sessions/user managers before SDDM restarts."""
    for user in users:
        backend._run(
            ["loginctl", "terminate-user", user],
            check=False,
            timeout=15,
        )

    # Give logind a short window to deallocate /run/user/<uid>, the D-Bus bus and
    # the per-user systemd manager. A fresh normal login then receives a clean
    # environment instead of the absolute per-seat Wayland socket imported by MSA.
    deadline = time.monotonic() + 8.0
    while users and time.monotonic() < deadline:
        remaining: list[str] = []
        for user in users:
            status = backend._run(
                ["loginctl", "show-user", user, "-p", "State", "--value"],
                check=False,
                timeout=3,
            )
            state = status.stdout.strip().lower()
            if status.returncode == 0 and state not in {"", "closing"}:
                remaining.append(user)
        if not remaining:
            break
        users = remaining
        time.sleep(0.2)


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v14_installed", False):
        return

    def restore_now() -> None:
        if backend.os.geteuid() != 0:
            raise PermissionError("Execute como root.")

        affected_users = _multiseat_users(backend)

        backend._run(["systemctl", "stop", backend.ACTIVATE_UNIT], check=False)
        backend.stop_transient_units(
            exclude={backend.RESTORE_UNIT},
            include_legacy=True,
        )

        backend.flush_inputs()

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

        # This is the missing half of restore: stopping the compositor does not
        # clear variables previously imported into systemd --user. Reset those
        # users before SDDM starts a normal Plasma session.
        _reset_multiseat_users(backend, affected_users)

        _restart_display_manager(backend)

    backend.restore_now = restore_now
    backend._msa_runtime_patch_v14_installed = True
