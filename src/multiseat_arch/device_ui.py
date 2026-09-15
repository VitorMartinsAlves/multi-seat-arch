from __future__ import annotations

import re
from dataclasses import dataclass

from .model import InputDevice

_USEFUL_KINDS = {"keyboard", "mouse", "touchpad", "gamepad"}
_SUFFIX_RE = re.compile(
    r"\s+(?:system control|consumer control)$",
    re.IGNORECASE,
)
_SYSTEM_NAMES = (
    "power button",
    "sleep button",
    "lid switch",
    "video bus",
    "pc speaker",
    "wireless radio control",
    "wmi hotkeys",
    "headphone",
    "hdmi/dp",
    "jack",
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
    return _SUFFIX_RE.sub("", cleaned).strip() or cleaned


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
    """Classify low-level controls that should normally remain on seat0."""
    low = device.name.lower()
    if any(token in low for token in _SYSTEM_NAMES):
        return True
    # Unknown platform/PCI/internal event nodes are normally ACPI, jack-detect or
    # vendor hotkey controls rather than a peripheral the user wants to route.
    return device.kind == "other" and device.bus.lower() in {
        "platform",
        "pci",
        "acpi",
        "interno",
        "",
    }


def is_useful_input(device: InputDevice) -> bool:
    """Return whether automatic assignment should move this input to a user seat."""
    return not is_system_device(device) and device.kind in _USEFUL_KINDS


def _group_kind(name: str, members: list[InputDevice]) -> str:
    """Pick the physical device type instead of an arbitrary composite interface."""
    low = name.lower()
    if "touchpad" in low:
        return "touchpad"
    if "keyboard" in low or "keypad" in low:
        return "keyboard"
    if "mouse" in low:
        return "mouse"
    if any(token in low for token in ("gamepad", "joystick", "controller")):
        return "gamepad"

    kinds = {item.kind for item in members}
    if len(kinds) == 1:
        return members[0].kind
    # Prefer keyboard over mouse for mixed HID groups unless the product name
    # clearly identifies a mouse. Gaming keyboards often expose relative axes or
    # media-control interfaces which udev can classify as mouse-like.
    priority = ("touchpad", "keyboard", "mouse", "gamepad", "other")
    return next(value for value in priority if value in kinds)


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
        name = min(names, key=lambda value: (len(value), value.lower()))
        kind = _group_kind(name, members)
        buses = {item.bus for item in members if item.bus}
        bus = members[0].bus if len(buses) <= 1 else "misto"
        seats = {item.seat for item in members}
        seat = members[0].seat if len(seats) == 1 else "misto"
        result.append(DeviceGroup(group_id, members, name, kind, bus, seat))
    return result
