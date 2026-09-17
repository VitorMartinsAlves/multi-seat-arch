from __future__ import annotations

from types import ModuleType

from . import audio
from .audio_seat import apply_runtime_audio_seats, clear_runtime_audio_seats


def _install_audio_description_fix() -> None:
    if getattr(audio, "_msa_audio_description_fix_installed", False):
        return

    previous = audio._outputs_from_json

    def outputs_from_json(raw):
        outputs = previous(raw)
        if not isinstance(raw, list):
            return outputs

        by_name = {
            str(item.get("name") or "").strip(): item
            for item in raw
            if isinstance(item, dict)
        }
        invalid = {"", "(null)", "null", "none", "unknown"}
        for output in outputs:
            if output.description.strip().lower() not in invalid:
                continue
            item = by_name.get(output.name, {})
            props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
            candidates = (
                props.get("node.description"),
                props.get("device.description"),
                props.get("alsa.card_name"),
                props.get("device.nick"),
                output.name,
            )
            for value in candidates:
                text = str(value or "").strip()
                if text and text.lower() not in invalid:
                    output.description = text
                    break
        return outputs

    audio._outputs_from_json = outputs_from_json
    audio._msa_audio_description_fix_installed = True


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v11_installed", False):
        return

    _install_audio_description_fix()

    previous_sync = backend.sync_devices_now
    previous_flush = backend.flush_inputs

    def sync_devices_now(config) -> None:
        previous_sync(config)
        # Apply before Atrium starts user sessions, so logind grants the target
        # user's PipeWire process only the ALSA hardware assigned to that seat.
        apply_runtime_audio_seats(config, backend)

    def flush_inputs() -> None:
        # Restore normal seat0 audio together with input devices. Audio cleanup
        # is best effort and must never prevent normal desktop recovery.
        try:
            clear_runtime_audio_seats(backend)
        finally:
            previous_flush()

    backend.sync_devices_now = sync_devices_now
    backend.flush_inputs = flush_inputs
    backend.RUNTIME_AUDIO_UDEV_RULES = __import__(
        "multiseat_arch.audio_seat", fromlist=["RUNTIME_AUDIO_UDEV_RULES"]
    ).RUNTIME_AUDIO_UDEV_RULES
    backend._msa_runtime_patch_v11_installed = True
