from __future__ import annotations

import glob
import hashlib
import os
import re
import subprocess
from pathlib import Path

from .model import Display, InputDevice


def _run(*args: str) -> str:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    ).stdout


def discover_displays(sys_class_drm: str = "/sys/class/drm") -> list[Display]:
    result: list[Display] = []
    for status_path in sorted(glob.glob(f"{sys_class_drm}/card*-*/status")):
        connector_dir = Path(status_path).parent
        connector = connector_dir.name
        card = connector.split("-", 1)[0]
        try:
            status = Path(status_path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        result.append(
            Display(
                connector=connector,
                card=card,
                status=status,
                syspath=os.path.realpath(connector_dir),
                name=connector,
            )
        )
    return result


def _kind_from_props(name: str, props: dict[str, str]) -> str:
    low = name.lower()
    if props.get("ID_INPUT_TOUCHPAD") == "1" or "touchpad" in low:
        return "touchpad"
    if props.get("ID_INPUT_MOUSE") == "1" or "mouse" in low:
        return "mouse"
    if props.get("ID_INPUT_KEYBOARD") == "1" or "keyboard" in low:
        return "keyboard"
    if props.get("ID_INPUT_JOYSTICK") == "1" or any(
        token in low for token in ("gamepad", "joystick", "controller")
    ):
        return "gamepad"
    return "other"


def parse_udev_properties(text: str) -> dict[str, str]:
    props: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        props[key] = value
    return props


def parse_udev_database(text: str) -> dict[str, tuple[dict[str, str], str]]:
    """Parse `udevadm info --export-db` entries for /dev/input/event* nodes.

    The GUI refreshes hardware periodically. Querying udev twice for every event
    node made a 25-input machine spawn about 50 subprocesses per refresh, which
    could block Qt long enough to look frozen. The export database gives us all
    metadata in one subprocess.
    """
    result: dict[str, tuple[dict[str, str], str]] = {}
    path = ""
    names: list[str] = []
    props: dict[str, str] = {}

    def commit() -> None:
        nonlocal path, names, props
        candidates = [f"/dev/{name}" for name in names if name.startswith("input/event")]
        devname = props.get("DEVNAME", "")
        if devname.startswith("/dev/input/event"):
            candidates.append(devname)
        for event in candidates:
            result[event] = (dict(props), path)
        path = ""
        names = []
        props = {}

    for line in text.splitlines() + [""]:
        if not line:
            if path or names or props:
                commit()
            continue
        if line.startswith("P: "):
            path = line[3:].strip()
        elif line.startswith("N: "):
            names.append(line[3:].strip())
        elif line.startswith("E: ") and "=" in line[3:]:
            key, value = line[3:].split("=", 1)
            props[key] = value

    return result


def parse_libinput(text: str) -> list[tuple[str, str]]:
    """Backward-compatible parser used by tests and migration tooling."""
    devices: list[tuple[str, str]] = []
    name = event = ""
    for line in text.splitlines() + [""]:
        if line.startswith("Device:"):
            if name and event:
                devices.append((name, event))
            name = line.split(":", 1)[1].strip()
            event = ""
        elif line.startswith("Kernel:"):
            event = line.split(":", 1)[1].strip()
        elif not line.strip() and name and event:
            devices.append((name, event))
            name = event = ""
    return devices


def _event_sort_key(path: str) -> tuple[int, str]:
    match = re.search(r"event(\d+)$", path)
    return (int(match.group(1)) if match else 10**9, path)


def _input_name(event: str, sys_class_input: str) -> str:
    event_name = Path(event).name
    name_path = Path(sys_class_input) / event_name / "device" / "name"
    try:
        return name_path.read_text(encoding="utf-8").strip()
    except OSError:
        return event_name


def _physical_syspath(syspath: str) -> str:
    return re.sub(r"/input/input\d+(?:/event\d+)?$", "", syspath)


def seat_assignable_syspath(syspath: str) -> str:
    """Return the seat-eligible input parent used by systemd-logind.

    `loginctl attach` only accepts devices tagged as seat-assignable by udev.
    For Linux input devices that is the `inputN` parent, not its `eventN` child.
    Keeping the event node in `InputDevice.event` still lets evdev read activity.
    """
    return re.sub(r"(/input/input\d+)/event\d+$", r"\1", syspath)


def _interface_identity(props: dict[str, str]) -> str:
    interface = props.get("ID_USB_INTERFACE_NUM", "").strip()
    if interface:
        return interface
    path = props.get("ID_PATH", "")
    matches = re.findall(r":(\d+\.\d+)(?=-|$)", path)
    return matches[-1] if matches else ""


def stable_device_key(
    name: str,
    kind: str,
    syspath: str,
    props: dict[str, str],
) -> str:
    """Build a persistent identity for one evdev function."""
    serial_short = props.get("ID_SERIAL_SHORT", "").strip()
    serial = props.get("ID_SERIAL", "").strip() if serial_short else ""
    path = (props.get("ID_PATH", "") or props.get("ID_PATH_TAG", "")).strip()
    interface = _interface_identity(props)
    if serial:
        identity = f"serial:{serial}|interface:{interface or '-'}"
    elif path:
        identity = f"path:{path}"
    else:
        identity = f"sysfs:{_physical_syspath(syspath)}"

    basis = f"{identity}|kind:{kind}|name:{name}"
    digest = hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:24]
    return f"input-{digest}"


def _input_function_identity(
    syspath: str,
    props: dict[str, str],
) -> str:
    """Fingerprint one evdev function inside a composite HID device.

    Some gaming mice expose several event nodes with the same product name,
    USB interface and udev path. Their input capabilities and HID collection
    index remain distinct, so use those only when the legacy stable key
    collides. This keeps existing keys unchanged for normal devices.
    """
    parent = Path(seat_assignable_syspath(syspath))
    parts: list[str] = []

    try:
        phys = (parent / "phys").read_text(encoding="utf-8").strip()
    except OSError:
        phys = ""
    match = re.search(r"/input(\d+)$", phys)
    if match:
        parts.append(f"collection:{match.group(1)}")

    caps = parent / "capabilities"
    for name in ("ev", "key", "rel", "abs", "msc", "sw", "led", "snd", "ff"):
        try:
            value = " ".join((caps / name).read_text(encoding="utf-8").split())
        except OSError:
            continue
        if value:
            parts.append(f"{name}:{value}")

    for prop in (
        "ID_INPUT_MOUSE",
        "ID_INPUT_KEYBOARD",
        "ID_INPUT_TOUCHPAD",
        "ID_INPUT_JOYSTICK",
        "ID_INPUT_KEY",
        "ID_INPUT_SWITCH",
    ):
        if props.get(prop) == "1":
            parts.append(prop)

    return "|".join(parts)


def _explicit_input_role_score(device: InputDevice, props: dict[str, str]) -> tuple[int, int]:
    role_prop = {
        "mouse": "ID_INPUT_MOUSE",
        "keyboard": "ID_INPUT_KEYBOARD",
        "touchpad": "ID_INPUT_TOUCHPAD",
        "gamepad": "ID_INPUT_JOYSTICK",
    }.get(device.kind, "")
    exact = 1 if role_prop and props.get(role_prop) == "1" else 0
    explicit = sum(
        props.get(prop) == "1"
        for prop in (
            "ID_INPUT_MOUSE",
            "ID_INPUT_KEYBOARD",
            "ID_INPUT_TOUCHPAD",
            "ID_INPUT_JOYSTICK",
        )
    )
    return exact, explicit


def _derived_collision_key(base_key: str, discriminator: str) -> str:
    digest = hashlib.sha256(
        f"{base_key}|function:{discriminator}".encode("utf-8", "replace")
    ).hexdigest()[:24]
    return f"input-{digest}"


def _disambiguate_colliding_device_keys(
    records: list[tuple[InputDevice, str, dict[str, str]]],
) -> None:
    """Make colliding composite-event keys unique without breaking old configs.

    The most explicit event node keeps the legacy key. For a mouse, for example,
    the node carrying ID_INPUT_MOUSE=1 wins. Existing configurations therefore
    keep routing the primary function, while sibling event nodes receive stable
    derived keys and can be migrated by the GUI as one physical group.
    """
    buckets: dict[str, list[tuple[InputDevice, str, dict[str, str]]]] = {}
    for record in records:
        buckets.setdefault(record[0].key, []).append(record)

    for base_key, bucket in buckets.items():
        if len(bucket) < 2:
            continue

        ordered = sorted(
            bucket,
            key=lambda item: (
                -_explicit_input_role_score(item[0], item[2])[0],
                -_explicit_input_role_score(item[0], item[2])[1],
                _event_sort_key(item[0].event),
            ),
        )

        used = {base_key}
        # Keep the first/primary event on the old key for config compatibility.
        for device, raw_syspath, props in ordered[1:]:
            discriminator = _input_function_identity(raw_syspath, props)
            if not discriminator:
                discriminator = f"parent:{Path(seat_assignable_syspath(raw_syspath)).name}"

            candidate = _derived_collision_key(base_key, discriminator)
            if candidate in used:
                # Last-resort uniqueness for truly indistinguishable kernel
                # functions. This is intentionally only a collision fallback.
                discriminator += f"|event:{Path(device.event).name}"
                candidate = _derived_collision_key(base_key, discriminator)
            device.key = candidate
            used.add(candidate)


def physical_group_key(syspath: str, props: dict[str, str]) -> str:
    """Build a UI-only identity for functions belonging to one physical device."""
    serial_short = props.get("ID_SERIAL_SHORT", "").strip()
    serial = props.get("ID_SERIAL", "").strip() if serial_short else ""
    if serial:
        basis = f"serial:{serial}"
    else:
        path = (props.get("ID_PATH", "") or props.get("ID_PATH_TAG", "")).strip()
        if path:
            path = re.sub(r":1\.\d+(?:-event-[^-]+)?$", "", path)
            path = re.sub(r"-event-[^-]+$", "", path)
            basis = f"path:{path}"
        else:
            physical = _physical_syspath(syspath)
            physical = re.sub(r"/[^/]+:\d+\.\d+$", "", physical)
            basis = f"sysfs:{physical}"
    digest = hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:20]
    return f"group-{digest}"


def discover_inputs(
    dev_input: str = "/dev/input",
    sys_class_input: str = "/sys/class/input",
) -> list[InputDevice]:
    """Discover real input devices using udev/sysfs as the source of truth."""
    result: list[InputDevice] = []
    records: list[tuple[InputDevice, str, dict[str, str]]] = []
    seen: set[str] = set()
    database = parse_udev_database(_run("udevadm", "info", "--export-db"))

    for event in sorted(glob.glob(f"{dev_input}/event*"), key=_event_sort_key):
        entry = database.get(event)
        if entry is not None:
            props, path = entry
        else:
            props = parse_udev_properties(
                _run("udevadm", "info", "--query=property", "--name", event)
            )
            path = _run("udevadm", "info", "--query=path", "--name", event).strip()

        name = _input_name(event, sys_class_input)
        if name.startswith("MSA Shared "):
            continue

        kind = _kind_from_props(name, props)
        if kind == "other" and props.get("ID_INPUT") != "1":
            continue

        if path.startswith("/devices/"):
            raw_syspath = f"/sys{path}"
        elif path.startswith("/sys/devices/"):
            raw_syspath = path
        else:
            candidate = Path(sys_class_input) / Path(event).name
            try:
                raw_syspath = str(candidate.resolve(strict=True))
            except OSError:
                continue

        if not raw_syspath.startswith("/sys/devices/"):
            continue

        syspath = seat_assignable_syspath(raw_syspath)
        if syspath in seen:
            continue
        seen.add(syspath)

        device = InputDevice(
            name=name,
            kind=kind,  # type: ignore[arg-type]
            event=event,
            syspath=syspath,
            bus=props.get("ID_BUS", ""),
            key=stable_device_key(name, kind, raw_syspath, props),
            seat=props.get("ID_SEAT", "seat0") or "seat0",
            group_key=physical_group_key(raw_syspath, props),
        )
        result.append(device)
        records.append((device, raw_syspath, props))

    _disambiguate_colliding_device_keys(records)
    return result


def discover_bluetooth_controllers() -> list[str]:
    """Return Bluetooth controllers; controllers remain global by design."""
    return [Path(path).name for path in sorted(glob.glob("/sys/class/bluetooth/hci*"))]


def connector_lease_name(connector: str) -> str:
    if not re.fullmatch(r"card\d+-[A-Za-z0-9_.:-]+", connector):
        raise ValueError(f"Conector inválido: {connector}")
    return connector