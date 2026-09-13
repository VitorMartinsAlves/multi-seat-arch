from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

InputKind = Literal["keyboard", "mouse", "touchpad", "gamepad", "other"]
DeviceMode = Literal["seat", "shared", "disabled", "unmanaged"]


@dataclass(slots=True)
class Display:
    connector: str
    card: str
    status: str
    syspath: str
    name: str = ""


@dataclass(slots=True)
class InputDevice:
    name: str
    kind: InputKind
    event: str
    syspath: str
    bus: str = ""
    key: str = ""
    seat: str = "seat0"


@dataclass(slots=True)
class DeviceRule:
    key: str
    mode: DeviceMode = "unmanaged"
    seat: str = ""
    name: str = ""


@dataclass(slots=True)
class Seat:
    name: str
    connector: str
    user: str
    inputs: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(slots=True)
class Config:
    version: int = 2
    compositor: str = "/usr/local/bin/labwc"
    seats: list[Seat] = field(default_factory=list)
    devices: list[DeviceRule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "compositor": self.compositor,
            "seats": [asdict(seat) for seat in self.seats],
            "devices": [asdict(rule) for rule in self.devices],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        if not isinstance(data, dict):
            raise ValueError("A configuração precisa ser um objeto JSON.")

        raw_seats = data.get("seats", [])
        if not isinstance(raw_seats, list):
            raise ValueError("'seats' precisa ser uma lista.")

        seats: list[Seat] = []
        for raw in raw_seats:
            if not isinstance(raw, dict):
                raise ValueError("Cada seat precisa ser um objeto.")
            unknown = set(raw) - {"name", "connector", "user", "inputs", "enabled"}
            if unknown:
                raise ValueError(
                    "Campos desconhecidos no seat: " + ", ".join(sorted(unknown))
                )
            inputs = raw.get("inputs", [])
            if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
                raise ValueError("'inputs' precisa ser uma lista de strings.")
            seats.append(
                Seat(
                    name=str(raw.get("name", "")),
                    connector=str(raw.get("connector", "")),
                    user=str(raw.get("user", "")),
                    inputs=inputs,
                    enabled=bool(raw.get("enabled", True)),
                )
            )

        raw_devices = data.get("devices", [])
        if not isinstance(raw_devices, list):
            raise ValueError("'devices' precisa ser uma lista.")
        devices: list[DeviceRule] = []
        for raw in raw_devices:
            if not isinstance(raw, dict):
                raise ValueError("Cada regra de dispositivo precisa ser um objeto.")
            unknown = set(raw) - {"key", "mode", "seat", "name"}
            if unknown:
                raise ValueError(
                    "Campos desconhecidos em devices: " + ", ".join(sorted(unknown))
                )
            mode = str(raw.get("mode", "unmanaged"))
            if mode not in {"seat", "shared", "disabled", "unmanaged"}:
                raise ValueError(f"Modo de dispositivo inválido: {mode}")
            devices.append(
                DeviceRule(
                    key=str(raw.get("key", "")),
                    mode=mode,  # type: ignore[arg-type]
                    seat=str(raw.get("seat", "")),
                    name=str(raw.get("name", "")),
                )
            )

        version = int(data.get("version", 1))
        # v1 migration: legacy syspaths stay on Seat.inputs. They are consumed by
        # the backend until the GUI saves the configuration as v2.
        if version not in {1, 2}:
            raise ValueError(f"Versão de configuração não suportada: {version}")

        return cls(
            version=2,
            compositor=str(data.get("compositor", "/usr/local/bin/labwc")),
            seats=seats,
            devices=devices,
        )
