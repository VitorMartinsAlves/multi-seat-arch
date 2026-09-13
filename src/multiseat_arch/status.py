from __future__ import annotations

import subprocess


def _active(unit: str) -> bool:
    return (
        subprocess.run(
            ["systemctl", "is-active", "--quiet", unit],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        ).returncode
        == 0
    )


def runtime_status() -> dict:
    proc = subprocess.run(
        ["systemctl", "list-units", "--all", "--plain", "--no-legend"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    seats: list[str] = []
    proxies: list[str] = []
    leases: list[str] = []
    for line in proc.stdout.splitlines():
        unit = line.split(maxsplit=1)[0] if line.strip() else ""
        if not unit or not unit.endswith(".service") or not _active(unit):
            continue
        if unit.startswith("msa-seat-"):
            seats.append(unit.removeprefix("msa-seat-").removesuffix(".service"))
        elif unit.startswith("msa-input-"):
            proxies.append(unit.removeprefix("msa-input-").removesuffix(".service"))
        elif unit.startswith("msa-dlm-"):
            leases.append(unit.removeprefix("msa-dlm-").removesuffix(".service"))

    return {
        "running": bool(seats),
        "seats": sorted(seats),
        "input_proxies": sorted(proxies),
        "drm_cards": sorted(leases),
        "hotplug": _active("msa-hotplug.service"),
    }
