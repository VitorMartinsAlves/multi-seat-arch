from __future__ import annotations

from .backend import sync_devices_now
from .model import Config
from .status import runtime_status


def sync_live(config: Config) -> None:
    """Apply device routing only when multiseat seats are already active.

    Calling loginctl flush-devices on a normal desktop and immediately moving
    its keyboard/mouse to non-running seats can lock the user out. Activation
    uses backend.sync_devices_now directly while the graphical target is down;
    this public live operation deliberately refuses that unsafe state.
    """
    status = runtime_status()
    if not status.get("running"):
        raise RuntimeError(
            "O multiseat não está ativo. Salve a configuração e use "
            "'Aplicar e iniciar'; a aplicação ao vivo só é permitida com "
            "seats em execução."
        )
    sync_devices_now(config)
