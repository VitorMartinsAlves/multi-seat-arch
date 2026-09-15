from __future__ import annotations

import hashlib
import os
import sys
import time
from collections.abc import Callable

from .backend import active_seats, sync_devices_now
from .discovery import discover_inputs
from .model import Config
from .operation import input_sync_lock
from .status import runtime_status


def _all_configured_seats_running(config: Config) -> bool:
    status = runtime_status()
    running = set(status.get("seats", []))
    expected = {seat.name for seat in active_seats(config)}
    return bool(status.get("running")) and expected.issubset(running)


def _fingerprint(config: Config) -> str:
    inventory = sorted(
        (device.key, device.event, device.syspath)
        for device in discover_inputs()
    )
    payload = repr((config.to_dict(), inventory)).encode("utf-8", "replace")
    return hashlib.sha256(payload).hexdigest()


def watch_inputs(
    config_loader: Callable[[], Config],
    interval: float = 1.5,
) -> None:
    """Reapply saved rules when the real evdev inventory changes."""
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")

    last_fingerprint = ""
    while True:
        try:
            config = config_loader()
            fingerprint = _fingerprint(config)
            if fingerprint != last_fingerprint:
                with input_sync_lock():
                    # Re-read after waiting so an old snapshot can never overwrite
                    # a newer saved configuration.
                    current = config_loader()
                    if not _all_configured_seats_running(current):
                        # A compositor may be restarting. Do not move physical
                        # inputs into a seat that currently has no consumer.
                        time.sleep(interval)
                        continue
                    sync_devices_now(current)
                    # Recompute after the sync because udev event numbers and the
                    # saved config may have changed while we waited for the lock.
                    last_fingerprint = _fingerprint(current)
        except Exception as exc:
            print(f"hotplug: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)
