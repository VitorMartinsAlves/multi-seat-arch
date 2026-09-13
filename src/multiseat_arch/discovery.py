from __future__ import annotations

import glob
import os
import re
import subprocess
from pathlib import Path
from .model import Display, InputDevice


def _run(*args: str) -> str:
    return subprocess.run(args, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout


def discover_displays(sys_class_drm: str = "/sys/class/drm") -> list[Display]:
    result: list[Display] = []
    for status_path in sorted(glob.glob(f"{sys_class_drm}/card*-*/status")):
        connector_dir = Path(status_path).parent
        connector = connector_dir.name
        card = connector.split("-", 1)[0]
        try:
            status = Path(status_path).read_text().strip()
        except OSError:
            continue
        result.append(Display(connector, card, status, os.path.realpath(connector_dir), connector))
    return result


def _kind_from_props(name: str, props: dict[str, str]) -> str:
    low = name.lower()
    if props.get("ID_INPUT_TOUCHPAD") == "1" or "touchpad" in low: return "touchpad"
    if props.get("ID_INPUT_MOUSE") == "1" or "mouse" in low: return "mouse"
    if props.get("ID_INPUT_KEYBOARD") == "1" or "keyboard" in low: return "keyboard"
    return "other"


def parse_libinput(text: str) -> list[tuple[str, str]]:
    devices: list[tuple[str, str]] = []
    name = event = ""
    for line in text.splitlines() + [""]:
        if line.startswith("Device:"):
            if name and event: devices.append((name, event))
            name = line.split(":", 1)[1].strip(); event = ""
        elif line.startswith("Kernel:"):
            event = line.split(":", 1)[1].strip()
        elif not line.strip() and name and event:
            devices.append((name, event)); name = event = ""
    return devices


def discover_inputs() -> list[InputDevice]:
    result: list[InputDevice] = []
    seen: set[str] = set()
    for name, event in parse_libinput(_run("libinput", "list-devices")):
        if event in seen: continue
        seen.add(event)
        props: dict[str, str] = {}
        for line in _run("udevadm", "info", "--query=property", "--name", event).splitlines():
            if "=" in line:
                k, v = line.split("=", 1); props[k] = v
        path = _run("udevadm", "info", "--query=path", "--name", event).strip()
        syspath = f"/sys{path}" if path.startswith("/devices/") else path
        result.append(InputDevice(name, _kind_from_props(name, props), event, syspath, props.get("ID_BUS", "")))
    return result


def connector_lease_name(connector: str) -> str:
    if not re.fullmatch(r"card\d+-.+", connector):
        raise ValueError(f"Conector inválido: {connector}")
    return connector
