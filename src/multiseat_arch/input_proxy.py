from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    from evdev import InputDevice as EvdevDevice
    from evdev import UInput, ecodes
except ImportError as exc:  # pragma: no cover - validated by doctor on target host
    raise SystemExit("python-evdev não está instalado") from exc


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def _event_syspath(event: str) -> str:
    output = _run("udevadm", "info", "--query=path", "--name", event).stdout.strip()
    if output.startswith("/devices/"):
        return "/sys" + output
    if output.startswith("/sys/devices/"):
        return output
    raise RuntimeError(f"Não foi possível resolver sysfs de {event}: {output}")


def _wait_uinput_path(ui: UInput, timeout: float = 5.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            device = ui.device
            path = getattr(device, "path", "")
            if path and Path(path).exists():
                return path
        except (AttributeError, OSError):
            pass
        time.sleep(0.05)
    raise RuntimeError("Dispositivo uinput virtual não apareceu.")


def _attach_virtual(ui: UInput, seat: str) -> str:
    event = _wait_uinput_path(ui)
    syspath = _event_syspath(event)
    proc = _run("loginctl", "attach", seat, syspath)
    if proc.returncode:
        raise RuntimeError(
            f"Falha ao anexar clone virtual a {seat}: {proc.stdout.strip()}"
        )
    _run("udevadm", "settle", "--timeout=5")
    return syspath


def _ready_path(path: str) -> Path:
    ready = Path(path)
    ready.parent.mkdir(parents=True, exist_ok=True)
    return ready


def _clone(device: EvdevDevice, seat: str) -> UInput:
    info = device.info
    # input_props is important for touchpads (INPUT_PROP_POINTER/DIRECT/etc.).
    # Without it a capability-identical clone may still be classified
    # differently by libinput. Identity fields also help gamepads and HID quirks.
    return UInput.from_device(
        device,
        name=f"MSA Shared {device.name} [{seat}]",
        phys=f"multi-seat-arch/{seat}",
        input_props=device.input_props(),
        bustype=info.bustype,
        vendor=info.vendor,
        product=info.product,
        version=info.version,
    )


def run_proxy(source: str, seats: list[str], ready_path: str) -> int:
    source_path = Path(source)
    if not source_path.exists():
        raise RuntimeError(f"Input não existe: {source}")

    device = EvdevDevice(source)
    outputs: list[UInput] = []
    running = True

    def stop(_signum, _frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    ready = _ready_path(ready_path)
    ready.unlink(missing_ok=True)

    try:
        # EVIOCGRAB makes 'disabled' reliable and prevents the physical event
        # node from also reaching seat0 while shared clones are active.
        device.grab()

        attached: dict[str, str] = {}
        for seat in seats:
            ui = _clone(device, seat)
            outputs.append(ui)
            attached[seat] = _attach_virtual(ui, seat)

        ready.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "source": source,
                    "name": device.name,
                    "seats": seats,
                    "virtual": attached,
                    "mode": "shared" if seats else "disabled",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        while running:
            try:
                events = list(device.read())
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except OSError:
                if running:
                    raise
                break

            if not events:
                time.sleep(0.005)
                continue
            for event in events:
                if event.type == ecodes.EV_SYN:
                    if event.code == ecodes.SYN_REPORT:
                        for ui in outputs:
                            ui.syn()
                    continue
                for ui in outputs:
                    ui.write(event.type, event.code, event.value)
        return 0
    finally:
        ready.unlink(missing_ok=True)
        try:
            device.ungrab()
        except OSError:
            pass
        for ui in outputs:
            try:
                ui.close()
            except OSError:
                pass
        device.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="multi-seat-arch-input-proxy")
    parser.add_argument("--source", required=True)
    parser.add_argument("--seat", action="append", default=[])
    parser.add_argument("--ready", required=True)
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        return run_proxy(args.source, args.seat, args.ready)
    except Exception as exc:
        print(f"Erro no proxy de input: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
