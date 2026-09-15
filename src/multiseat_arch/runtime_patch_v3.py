from __future__ import annotations

import os
import time
from pathlib import Path
from types import ModuleType


def install(backend: ModuleType) -> None:
    """Create real logind seats from DRM connector master devices.

    The target Intel Ice Lake host can run two DRM-leased labwc compositors, but
    libseat/logind will not expose seat-scoped input devices unless the custom
    XDG_SEAT names exist as actual logind seats.  Upstream multiseat achieves
    that by attaching the DRM connector as a master-of-seat device.  We do the
    equivalent with ephemeral udev rules under /run.
    """
    if getattr(backend, "_msa_runtime_patch_v3_installed", False):
        return

    previous_write_rules = backend._write_runtime_udev_rules
    previous_activate = backend.activate_now

    def connector_syspath(connector: str) -> str:
        path = Path("/sys/class/drm") / connector
        try:
            return str(path.resolve(strict=True))
        except OSError as exc:
            raise RuntimeError(f"Conector DRM não encontrado: {connector}") from exc

    def write_rules(config, assignments: list[tuple[str, str]]) -> None:
        previous_write_rules(config, assignments)
        target = backend.RUNTIME_UDEV_RULES
        lines = [line for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]

        for seat in backend.active_seats(config):
            runtime = backend.runtime_seat_name(seat)
            syspath = connector_syspath(seat.connector)
            devpath = backend._udev_escape(syspath.removeprefix("/sys"))
            value = backend._udev_escape(runtime)
            kernel = Path(syspath).name
            rule = (
                f'SUBSYSTEM=="drm", KERNEL=="{kernel}", DEVPATH=="{devpath}", '
                f'ENV{{ID_SEAT}}="{value}", TAG+="seat", TAG+="master-of-seat"'
            )
            if rule not in lines:
                lines.append(rule)

        tmp = target.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, target)
        backend._run(["udevadm", "control", "--reload"], check=False)
        backend._run(["udevadm", "trigger", "--subsystem-match=drm", "--action=change"], check=False)
        backend._run(["udevadm", "trigger", "--subsystem-match=input", "--action=change"], check=False)
        backend._run(["udevadm", "settle", "--timeout=5"], check=False)

    def wait_logind_seats(config, timeout: float = 8.0) -> None:
        expected = {backend.runtime_seat_name(seat) for seat in backend.active_seats(config)}
        deadline = time.monotonic() + timeout
        missing = set(expected)
        while missing and time.monotonic() < deadline:
            out = backend._run(["loginctl", "list-seats", "--no-legend"], check=False).stdout
            present = {parts[0] for line in out.splitlines() if (parts := line.split())}
            missing = expected - present
            if missing:
                time.sleep(0.15)
        if missing:
            raise RuntimeError("logind não criou os seats de hardware: " + ", ".join(sorted(missing)))

    def activate(config) -> None:
        original_sync = backend.sync_devices_now

        def sync_with_real_seats(cfg) -> None:
            original_sync(cfg)
            wait_logind_seats(cfg)

        backend.sync_devices_now = sync_with_real_seats
        try:
            previous_activate(config)
        finally:
            backend.sync_devices_now = original_sync

    backend._write_runtime_udev_rules = write_rules
    backend.activate_now = activate
    backend._msa_runtime_patch_v3_installed = True
