from __future__ import annotations

import os
from pathlib import Path

from .audio import apply_for_current_seat
from .plasma_session import main as plasma_main


def _ensure_flatpak_exports() -> None:
    """Mirror the XDG data paths a normal Plasma login gets for Flatpak apps."""
    data_dirs = [part for part in os.environ.get("XDG_DATA_DIRS", "").split(":") if part]
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    flatpak_dirs = [
        str(data_home / "flatpak" / "exports" / "share"),
        "/var/lib/flatpak/exports/share",
    ]
    for item in flatpak_dirs:
        if item not in data_dirs:
            data_dirs.append(item)
    os.environ["XDG_DATA_DIRS"] = ":".join(data_dirs)


def main() -> int:
    # The custom leased Plasma session does not pass through the normal distro
    # login environment, so add Flatpak export directories before Plasma builds
    # its KService application cache. This makes Discover-installed apps visible
    # in Kickoff and lets Discover resolve their desktop launchers.
    _ensure_flatpak_exports()

    # Best-effort: PipeWire-Pulse may still be starting during very early login.
    # The first call normally succeeds; the Plasma session itself remains usable
    # even when no audio rule or audio service is available.
    try:
        apply_for_current_seat()
    except Exception:
        pass
    return plasma_main()


if __name__ == "__main__":
    raise SystemExit(main())
