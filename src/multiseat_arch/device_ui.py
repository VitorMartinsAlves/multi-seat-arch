from __future__ import annotations

import re
from dataclasses import dataclass

from .model import InputDevice

_USEFUL_KINDS = {"keyboard", "mouse", "touchpad", "gamepad"}
_SUFFIX_RE = re.compile(
    r"\s+(?:system control|consumer control|keyboard|mouse|touchpad)$",
    re.IGNORECASE,
)


@dataclass(slots=True)
class DeviceGroup:
    """One visual row that may represent several evdev functions."""

    id: str
    devices: list[InputDevice]
    name: str
    kind: str
    bus: str
    seat: str

    @property
    def keys(self) -> list[str]:
        return [device.key for device in self.devices]


def clean_device_name(name: str) -> str:
    """Remove common composite-interface suffixes without hiding the product name."""
    cleaned = name.strip()
    previous = None
    while previous != cleaned:
        previous = cleaned
        cleaned = _SUFFIX_RE.sub("", cleaned).strip()
    return cleaned or name.strip()


def icon_names(kind: str, bus: str = "") -> tuple[str, ...]:
    """Return Freedesktop/Breeze icon candidates in preference order."""
    if kind == "keyboard":
        return ("input-keyboard-symbolic", "input-keyboard", "preferences-desktop-keyboard")
    if kind == "mouse":
        return ("input-mouse-symbolic", "input-mouse", "preferences-desktop-mouse")
    if kind == "touchpad":
        return ("input-touchpad-symbolic", "input-touchpad", "preferences-desktop-touchpad")
    if kind == "gamepad":
        return ("input-gaming-symbolic", "input-gaming", "applications-games")
    if bus.lower() == "bluetooth":
        return ("bluetooth-symbolic", "bluetooth-active", "bluetooth")
    return ("input-dialpad-symbolic", "preferences-system", "applications-system")


def is_system_device(device: InputDevice) -> bool:
    """Classify low-level switches/buttons that normally should remain on seat0."""
    if device.kind != "other":
        return False
    low = device.name.lower()
    return any(
        token in low
        for token in (
            "power button",
            "sleep button",
            "lid switch",
            "video bus",
            "pc speaker",
        )
    )


def is_useful_input(device: InputDevice) -> bool:
    """Return whether automatic assignment should move this input to a user seat."""
    return device.kind in _USEFUL_KINDS and not is_system_device(device)


def group_devices(
    devices: list[InputDevice], *, group_interfaces: bool = True
) -> list[DeviceGroup]:
    """Group USB/Bluetooth composite functions while keeping routing keys intact."""
    buckets: dict[str, list[InputDevice]] = {}
    order: list[str] = []
    for device in devices:
        can_group = (
            group_interfaces
            and bool(device.group_key)
            and device.bus.lower() in {"usb", "bluetooth"}
        )
        group_id = device.group_key if can_group else device.key
        if group_id not in buckets:
            buckets[group_id] = []
            order.append(group_id)
        buckets[group_id].append(device)

    result: list[DeviceGroup] = []
    for group_id in order:
        members = buckets[group_id]
        names = [clean_device_name(item.name) for item in members]
        # Prefer the shortest normalized name: composite interfaces usually append
        # "Consumer Control" / "System Control" to the product name.
        name = min(names, key=lambda value: (len(value), value.lower()))
        kinds = {item.kind for item in members}
        kind = members[0].kind if len(kinds) == 1 else "other"
        buses = {item.bus for item in members if item.bus}
        bus = members[0].bus if len(buses) <= 1 else "misto"
        seats = {item.seat for item in members}
        seat = members[0].seat if len(seats) == 1 else "misto"
        result.append(DeviceGroup(group_id, members, name, kind, bus, seat))
    return result
