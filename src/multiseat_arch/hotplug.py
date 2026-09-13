from __future__ import annotations

import hashlib
import os
import sys
import time
from collections.abc import Callable

from .backend import sync_devices_now
from .discovery import discover_inputs
from .model import Config
from .operation import input_sync_lock


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
            inventory = sorted(
                (device.key, device.event, device.syspath)
                for device in discover_inputs()
            )
            payload = repr((config.to_dict(), inventory)).encode(
                "utf-8", "replace"
            )
            fingerprint = hashlib.sha256(payload).hexdigest()
            if fingerprint != last_fingerprint:
                with input_sync_lock():
                    # Re-read after waiting for another manual sync so an old
                    # snapshot can never overwrite a newer saved configuration.
                    current = config_loader()
                    sync_devices_now(current)
                last_fingerprint = fingerprint
        except Exception as exc:
            print(f"hotplug: {exc}", file=sys.stderr, flush=True)
        time.sleep(interval)
