from __future__ import annotations

import json
import math
import os
import shutil
import struct
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

AUDIO_CONFIG = Path("/etc/multi-seat-arch/audio.json")


@dataclass(slots=True)
class AudioOutput:
    name: str
    description: str
    state: str
    bus: str = ""


@dataclass(slots=True)
class AudioRule:
    output: str
    seat: str
    description: str = ""


def _run(command: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(command, 127, "")


def discover_outputs() -> list[AudioOutput]:
    pactl = shutil.which("pactl")
    if not pactl:
        return []
    result = _run([pactl, "-f", "json", "list", "sinks"])
    if result.returncode:
        return []
    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []

    outputs: list[AudioOutput] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
        description = str(
            item.get("description")
            or props.get("device.description")
            or props.get("node.description")
            or name
        )
        bus = str(props.get("device.bus") or props.get("device.api") or "")
        outputs.append(
            AudioOutput(
                name=name,
                description=description,
                state=str(item.get("state") or "UNKNOWN").upper(),
                bus=bus,
            )
        )
    outputs.sort(key=lambda item: (item.description.lower(), item.name))
    return outputs


def load_rules() -> list[AudioRule]:
    try:
        data = json.loads(AUDIO_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw_rules = data.get("outputs", []) if isinstance(data, dict) else []
    result: list[AudioRule] = []
    for raw in raw_rules if isinstance(raw_rules, list) else []:
        if not isinstance(raw, dict):
            continue
        output = str(raw.get("output") or "")
        seat = str(raw.get("seat") or "")
        if output and seat in {"seat-a", "seat-b", "unmanaged"}:
            result.append(
                AudioRule(
                    output=output,
                    seat=seat,
                    description=str(raw.get("description") or ""),
                )
            )
    return result


def save_rules_from_file(source: str) -> None:
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
        if not output or seat not in {"seat-a", "seat-b", "unmanaged"}:
            raise ValueError("Saída/seat de áudio inválido.")
        if output in seen:
            raise ValueError(f"Saída de áudio duplicada: {output}")
        seen.add(output)
        clean.append({"output": output, "seat": seat, "description": description})

    AUDIO_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = AUDIO_CONFIG.with_name(f".{AUDIO_CONFIG.name}.tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps({"version": 1, "outputs": clean}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o644)
        tmp.replace(AUDIO_CONFIG)
    finally:
        tmp.unlink(missing_ok=True)


def _test_wav() -> str:
    handle = tempfile.NamedTemporaryFile(prefix="msa-audio-test-", suffix=".wav", delete=False)
    path = handle.name
    handle.close()
    rate = 48000
    duration = 0.65
    frames = int(rate * duration)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        payload = bytearray()
        for i in range(frames):
            envelope = min(1.0, i / (rate * 0.03), (frames - i) / (rate * 0.05))
            sample = int(11000 * envelope * math.sin(2 * math.pi * 660 * i / rate))
            payload.extend(struct.pack("<hh", sample, sample))
        wav.writeframes(bytes(payload))
    return path


def test_output(output_name: str) -> tuple[bool, str]:
    wav = _test_wav()
    try:
        paplay = shutil.which("paplay")
        if paplay:
            result = _run([paplay, f"--device={output_name}", wav], timeout=5.0)
            return result.returncode == 0, result.stdout.strip()
        return False, "paplay não encontrado (instale pulseaudio-utils/pipewire-pulse)."
    finally:
        Path(wav).unlink(missing_ok=True)


def apply_for_current_seat() -> None:
    runtime_seat = os.environ.get("XDG_SEAT", "")
    if not runtime_seat:
        return

    # Import here to avoid backend/config side effects in the GUI discovery path.
    from . import config as cfg
    from .backend import runtime_seat_name

    try:
        config = cfg.load()
    except Exception:
        return
    logical = next(
        (seat.name for seat in config.seats if seat.enabled and runtime_seat_name(seat) == runtime_seat),
        "",
    )
    if not logical:
        return
    rule = next((item for item in load_rules() if item.seat == logical), None)
    if rule is None:
        return

    pactl = shutil.which("pactl")
    if pactl:
        # PipeWire-Pulse keeps the default per logged-in user/session, which is
        # exactly what we want for dynamic users on a fixed physical seat.
        _run([pactl, "set-default-sink", rule.output])
