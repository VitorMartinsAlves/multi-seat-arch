from __future__ import annotations

import fcntl
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_PATH = Path("/run/multi-seat-arch/input-sync.lock")


@contextmanager
def input_sync_lock() -> Iterator[None]:
    """Serialize device flush/attach/proxy operations across processes."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
