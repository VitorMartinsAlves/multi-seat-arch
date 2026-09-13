from __future__ import annotations

from .backend import sync_devices_now
from .model import Config
from .operation import input_sync_lock
from .status import runtime_status


def ensure_multiseat_running() -> None:
    if not runtime_status().get("running"):
        raise RuntimeError(
            "O multiseat não está ativo. Salve a configuração e use "
            "'Aplicar e iniciar'; a aplicação ao vivo só é permitida com "
            "seats em execução."
        )


def sync_live(config: Config) -> None:
    """Safely apply device routing while graphical multiseat seats are active."""
    ensure_multiseat_running()
    with input_sync_lock():
        # Re-check after waiting: the seats could have been restored while this
        # process was blocked behind a hotplug/manual operation.
        ensure_multiseat_running()
        sync_devices_now(config)
