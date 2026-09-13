from __future__ import annotations

import subprocess

from .backend import ACTIVATE_UNIT, RESTORE_UNIT


def _stop(unit: str) -> None:
    subprocess.run(
        ["systemctl", "stop", unit],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    subprocess.run(
        ["systemctl", "reset-failed", unit],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def before_activation() -> None:
    """A new activation supersedes a still-running restore helper."""
    _stop(RESTORE_UNIT)


def before_restore() -> None:
    """Recovery always wins over an in-flight activation."""
    _stop(ACTIVATE_UNIT)
