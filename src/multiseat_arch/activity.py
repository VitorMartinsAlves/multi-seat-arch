from __future__ import annotations

import select
import threading
from collections.abc import Iterable

from PyQt6.QtCore import QObject, pyqtSignal

from .model import InputDevice

try:
    from evdev import InputDevice as EvdevInputDevice
except ImportError:  # pragma: no cover - installer provides python-evdev
    EvdevInputDevice = None  # type: ignore[assignment]


class InputActivityMonitor(QObject):
    """Watch evdev activity for UI identification without EVIOCGRAB.

    Each event node is opened read-only. Linux evdev maintains an independent
    queue per open file descriptor, so observing activity here does not steal
    events from the compositor or applications.
    """

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
        """Replace the event->stable-key inventory watched by the background thread."""
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
        """Stop the watcher promptly when the GUI exits."""
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
        try:
            while not self._stop.is_set():
                generation, wanted = self._snapshot()
                if generation != active_generation:
                    self._close_all(opened)
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
                    ready, _write, _error = select.select(
                        list(opened), [], [], 0.25
                    )
                except (OSError, ValueError):
                    # Hot-unplug can invalidate an fd between refreshes. The GUI's
                    # hardware timer will publish a new generation shortly.
                    self._stop.wait(0.1)
                    continue

                for fd in ready:
                    entry = opened.get(fd)
                    if entry is None:
                        continue
                    key, device = entry
                    try:
                        events = device.read()  # type: ignore[attr-defined]
                    except (OSError, BlockingIOError):
                        try:
                            device.close()  # type: ignore[attr-defined]
                        except OSError:
                            pass
                        opened.pop(fd, None)
                        continue
                    if events:
                        # One pulse per read batch is enough; mouse motion can emit
                        # hundreds of events per second.
                        self.activity.emit(key)
        finally:
            self._close_all(opened)
