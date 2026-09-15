from __future__ import annotations

from .backend import active_seats, sync_devices_now
from .model import Config
from .operation import input_sync_lock
from .status import runtime_status


def ensure_multiseat_running(config: Config | None = None) -> None:
    status = runtime_status()
    running = set(status.get("seats", []))
    if not status.get("running"):
        raise RuntimeError(
            "O multiseat não está ativo. Salve a configuração e use "
            "'Aplicar e iniciar'; a aplicação ao vivo só é permitida com "
            "seats em execução."
        )

    if config is not None:
        expected = {seat.name for seat in active_seats(config)}
        missing = sorted(expected - running)
        if missing:
            raise RuntimeError(
                "Não é seguro aplicar periféricos: os seguintes seats configurados "
                "não estão ativos: " + ", ".join(missing) + ". Reinicie o multiseat "
                "ou restaure o PC normal antes de tentar novamente."
            )


def sync_live(config: Config) -> None:
    """Safely apply device routing while all configured seats are active."""
    ensure_multiseat_running(config)
    with input_sync_lock():
        # Re-check after waiting: a seat could have failed or been restored while
        # this process was blocked behind a hotplug/manual operation.
        ensure_multiseat_running(config)
        sync_devices_now(config)
