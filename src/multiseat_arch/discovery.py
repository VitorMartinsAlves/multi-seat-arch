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


def stable_device_key(
    name: str,
    kind: str,
    syspath: str,
    props: dict[str, str],
) -> str:
    basis = "|".join(
        part
        for part in (
            props.get("ID_SERIAL", ""),
            props.get("ID_PATH", ""),
            props.get("ID_PATH_TAG", ""),
            _physical_syspath(syspath),
            kind,
            name,
        )
        if part
    )
    digest = hashlib.sha256(basis.encode("utf-8", "replace")).hexdigest()[:24]
    return f"input-{digest}"


def discover_inputs(
    dev_input: str = "/dev/input",
    sys_class_input: str = "/sys/class/input",
) -> list[InputDevice]:
    """Discover real input devices using udev/sysfs as the source of truth."""
    result: list[InputDevice] = []
    seen: set[str] = set()

    for event in sorted(glob.glob(f"{dev_input}/event*"), key=_event_sort_key):
        props = parse_udev_properties(
            _run("udevadm", "info", "--query=property", "--name", event)
        )
        name = _input_name(event, sys_class_input)
        # Do not feed the uinput clones created by input_proxy back into the
        # inventory; otherwise hotplug sync would recursively clone its clones.
        if name.startswith("MSA Shared "):
            continue

        kind = _kind_from_props(name, props)
        if kind == "other" and props.get("ID_INPUT") != "1":
            continue

        path = _run(
            "udevadm", "info", "--query=path", "--name", event
        ).strip()
        if path.startswith("/devices/"):
            syspath = f"/sys{path}"
        elif path.startswith("/sys/devices/"):
            syspath = path
        else:
            candidate = Path(sys_class_input) / Path(event).name
            try:
                syspath = str(candidate.resolve(strict=True))
            except OSError:
                continue

        if not syspath.startswith("/sys/devices/") or syspath in seen:
            continue
        seen.add(syspath)

        result.append(
            InputDevice(
                name=name,
                kind=kind,  # type: ignore[arg-type]
                event=event,
                syspath=syspath,
                bus=props.get("ID_BUS", ""),
                key=stable_device_key(name, kind, syspath, props),
                seat=props.get("ID_SEAT", "seat0") or "seat0",
            )
        )

    return result


def discover_bluetooth_controllers() -> list[str]:
    """Return Bluetooth controllers; controllers remain global by design."""
    return [Path(path).name for path in sorted(glob.glob("/sys/class/bluetooth/hci*"))]


def connector_lease_name(connector: str) -> str:
    if not re.fullmatch(r"card\d+-[A-Za-z0-9_.:-]+", connector):
        raise ValueError(f"Conector inválido: {connector}")
    return connector
