from __future__ import annotations

import json
import os
import re
from pathlib import Path
from types import ModuleType

from . import audio, audio_seat

_SEAT_RE = re.compile(r"seat-[A-Za-z0-9_-]+$")


def _valid_audio_destination(value: str) -> bool:
    return value == "unmanaged" or bool(_SEAT_RE.fullmatch(value))


def _load_rules_dynamic() -> list[audio.AudioRule]:
    try:
        data = json.loads(audio.AUDIO_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_rules = data.get("outputs", []) if isinstance(data, dict) else []
    result: list[audio.AudioRule] = []
    for raw in raw_rules if isinstance(raw_rules, list) else []:
        if not isinstance(raw, dict):
            continue
        output = str(raw.get("output") or "").strip()
        seat = str(raw.get("seat") or "").strip()
        if output and _valid_audio_destination(seat):
            result.append(
                audio.AudioRule(
                    output=output,
                    seat=seat,
                    description=str(raw.get("description") or ""),
                )
            )
    return result


def _save_rules_dynamic(source: str) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    data = json.loads(Path(source).read_text(encoding="utf-8"))
    raw_rules = data.get("outputs", []) if isinstance(data, dict) else []
    clean: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in raw_rules if isinstance(raw_rules, list) else []:
        if not isinstance(raw, dict):
            raise ValueError("Regra de áudio inválida.")
        output = str(raw.get("output") or "").strip()
        seat = str(raw.get("seat") or "").strip()
        description = str(raw.get("description") or "").strip()
        if not output or not _valid_audio_destination(seat):
            raise ValueError("Saída/seat de áudio inválido.")
        if output in seen:
            raise ValueError(f"Saída de áudio duplicada: {output}")
        seen.add(output)
        clean.append({"output": output, "seat": seat, "description": description})

    audio.AUDIO_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = audio.AUDIO_CONFIG.with_name(f".{audio.AUDIO_CONFIG.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(
            json.dumps({"version": 1, "outputs": clean}, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.chmod(tmp, 0o644)
        tmp.replace(audio.AUDIO_CONFIG)
    finally:
        tmp.unlink(missing_ok=True)


def _load_audio_seat_rules_dynamic() -> list[dict[str, str]]:
    try:
        raw = json.loads(audio_seat.AUDIO_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    outputs = raw.get("outputs", []) if isinstance(raw, dict) else []
    result: list[dict[str, str]] = []
    for item in outputs if isinstance(outputs, list) else []:
        if not isinstance(item, dict):
            continue
        output = str(item.get("output") or "").strip()
        seat = str(item.get("seat") or "").strip()
        if output and _SEAT_RE.fullmatch(seat):
            result.append({"output": output, "seat": seat})
    return result


def install(_backend: ModuleType) -> None:
    if getattr(audio, "_msa_dynamic_audio_seats_installed", False):
        return
    audio.load_rules = _load_rules_dynamic
    audio.save_rules_from_file = _save_rules_dynamic
    audio_seat._load_audio_rules = _load_audio_seat_rules_dynamic
    audio._msa_dynamic_audio_seats_installed = True
