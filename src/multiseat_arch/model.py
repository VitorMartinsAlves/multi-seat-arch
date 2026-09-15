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

    @staticmethod
    def _string(raw: dict, key: str, default: str = "") -> str:
        value = raw.get(key, default)
        if not isinstance(value, str):
            raise ValueError(f"'{key}' precisa ser uma string.")
        return value

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        if not isinstance(data, dict):
            raise ValueError("A configuração precisa ser um objeto JSON.")

        unknown_top = set(data) - {"version", "compositor", "seats", "devices"}
        if unknown_top:
            raise ValueError(
                "Campos desconhecidos na configuração: "
                + ", ".join(sorted(unknown_top))
            )

        raw_version = data.get("version", 1)
        if isinstance(raw_version, bool) or not isinstance(raw_version, int):
            raise ValueError("'version' precisa ser um inteiro.")
        if raw_version not in {1, 2}:
            raise ValueError(
                f"Versão de configuração não suportada: {raw_version}"
            )

        compositor = data.get("compositor", "/usr/local/bin/labwc")
        if not isinstance(compositor, str):
            raise ValueError("'compositor' precisa ser uma string.")

        raw_seats = data.get("seats", [])
        if not isinstance(raw_seats, list):
            raise ValueError("'seats' precisa ser uma lista.")

        seats: list[Seat] = []
        legacy_input_owner: dict[str, str] = {}
        for raw in raw_seats:
            if not isinstance(raw, dict):
                raise ValueError("Cada seat precisa ser um objeto.")
            unknown = set(raw) - {"name", "connector", "user", "inputs", "enabled"}
            if unknown:
                raise ValueError(
                    "Campos desconhecidos no seat: " + ", ".join(sorted(unknown))
                )
            inputs = raw.get("inputs", [])
            if not isinstance(inputs, list) or not all(
                isinstance(item, str) for item in inputs
            ):
                raise ValueError("'inputs' precisa ser uma lista de strings.")
            enabled = raw.get("enabled", True)
            if not isinstance(enabled, bool):
                raise ValueError("'enabled' precisa ser booleano.")
            name = cls._string(raw, "name")
            for syspath in inputs:
                owner = legacy_input_owner.get(syspath)
                if owner is not None and owner != name:
                    raise ValueError(
                        f"Input legado usado por mais de um seat: {syspath} "
                        f"({owner}, {name})"
                    )
                legacy_input_owner[syspath] = name
            seats.append(
                Seat(
                    name=name,
                    connector=cls._string(raw, "connector"),
                    user=cls._string(raw, "user"),
                    inputs=inputs,
                    enabled=enabled,
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
            mode = cls._string(raw, "mode", "unmanaged")
            if mode not in {"seat", "shared", "disabled", "unmanaged"}:
                raise ValueError(f"Modo de dispositivo inválido: {mode}")
            devices.append(
                DeviceRule(
                    key=cls._string(raw, "key"),
                    mode=mode,  # type: ignore[arg-type]
                    seat=cls._string(raw, "seat"),
                    name=cls._string(raw, "name"),
                )
            )

        # v1 migration: legacy syspaths remain in Seat.inputs and are consumed
        # until the visual editor saves a native v2 device rule configuration.
        return cls(
            version=2,
            compositor=compositor,
            seats=seats,
            devices=devices,
        )
