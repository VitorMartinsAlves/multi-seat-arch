from __future__ import annotations

from .audio import apply_for_current_seat
from .plasma_session import main as plasma_main


def main() -> int:
    # Best-effort: PipeWire-Pulse may still be starting during very early login.
    # The first call normally succeeds; the Plasma session itself remains usable
    # even when no audio rule or audio service is available.
    try:
        apply_for_current_seat()
    except Exception:
        pass
    return plasma_main()


if __name__ == "__main__":
    raise SystemExit(main())
