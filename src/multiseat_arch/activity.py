from __future__ import annotations

import select
import threading
import time
from collections.abc import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from .model import InputDevice

try:
    from evdev import InputDevice as EvdevInputDevice, ecodes
except ImportError:  # pragma: no cover - installer provides python-evdev
    EvdevInputDevice = None  # type: ignore[assignment]
    ecodes = None  # type: ignore[assignment]


class _ActivityRateLimiter:
    """Bound UI notifications so high-rate mice cannot flood Qt's event queue."""

    def __init__(self, interval: float = 0.65) -> None:
        self.interval = interval
        self._last: dict[str, float] = {}

    def allow(self, key: str, now: float) -> bool:
        previous = self._last.get(key)
        if previous is not None and now - previous < self.interval:
            return False
        self._last[key] = now
        return True

    def reset(self) -> None:
        self._last.clear()


def _meaningful_events(events: list[object]) -> bool:
    """Ignore SYN/MSC heartbeats and zero-value noise from gaming HID devices."""
    if ecodes is None:
        return bool(events)
    for event in events:
        event_type = getattr(event, "type", None)
        value = getattr(event, "value", 0)
        if event_type == ecodes.EV_KEY and value in {1, 2}:
            return True
        if event_type == ecodes.EV_REL and value != 0:
            return True
        if event_type == ecodes.EV_ABS:
            return True
    return False


class InputActivityMonitor(QObject):
    """Watch evdev activity for UI identification without EVIOCGRAB."""

    activity = pyqtSignal(str)
    availability = pyqtSignal(int, int)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._wanted: dict[str, str] = {}
        self._generation = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            name="msa-input-activity",
            daemon=True,
        )
        self._thread.start()

    def set_devices(self, devices: Iterable[InputDevice]) -> None:
        wanted = {
            device.event: device.key
            for device in devices
            if device.event and device.key and device.kind != "other"
        }
        with self._lock:
            if wanted == self._wanted:
                return
            self._wanted = wanted
            self._generation += 1

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _snapshot(self) -> tuple[int, dict[str, str]]:
        with self._lock:
            return self._generation, dict(self._wanted)

    @staticmethod
    def _close_all(opened: dict[int, tuple[str, object]]) -> None:
        for _fd, (_key, device) in list(opened.items()):
            try:
                device.close()  # type: ignore[attr-defined]
            except OSError:
                pass
        opened.clear()

    def _worker(self) -> None:
        opened: dict[int, tuple[str, object]] = {}
        active_generation = -1
        limiter = _ActivityRateLimiter()
        try:
            while not self._stop.is_set():
                generation, wanted = self._snapshot()
                if generation != active_generation:
                    self._close_all(opened)
                    limiter.reset()
                    active_generation = generation
                    if EvdevInputDevice is not None:
                        for event_path, key in wanted.items():
                            try:
                                device = EvdevInputDevice(event_path)
                                opened[device.fd] = (key, device)
                            except (OSError, PermissionError):
                                continue
                    self.availability.emit(len(opened), len(wanted))

                if not opened:
                    self._stop.wait(0.25)
                    continue

                try:
                    ready, _write, _error = select.select(list(opened), [], [], 0.25)
                except (OSError, ValueError):
                    self._stop.wait(0.1)
                    continue

                for fd in ready:
                    entry = opened.get(fd)
                    if entry is None:
                        continue
                    key, device = entry
                    try:
                        events = list(device.read())  # type: ignore[attr-defined]
                    except (OSError, BlockingIOError):
                        try:
                            device.close()  # type: ignore[attr-defined]
                        except OSError:
                            pass
                        opened.pop(fd, None)
                        continue
                    if _meaningful_events(events) and limiter.allow(key, time.monotonic()):
                        self.activity.emit(key)
        finally:
            self._close_all(opened)
