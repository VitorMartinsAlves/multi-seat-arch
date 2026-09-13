from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

InputKind = Literal["keyboard", "mouse", "touchpad", "other"]


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


@dataclass(slots=True)
class Seat:
    name: str
    connector: str
    user: str
    inputs: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Config:
    version: int = 1
    compositor: str = "/usr/local/bin/labwc"
    seats: list[Seat] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "compositor": self.compositor,
            "seats": [asdict(seat) for seat in self.seats],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        raw_seats = data.get("seats", [])
        if not isinstance(raw_seats, list):
            raise ValueError("'seats' precisa ser uma lista.")

        seats: list[Seat] = []
        for raw in raw_seats:
            if not isinstance(raw, dict):
                raise ValueError("Cada seat precisa ser um objeto.")
            unknown = set(raw) - {"name", "connector", "user", "inputs"}
            if unknown:
                raise ValueError(
                    "Campos desconhecidos no seat: " + ", ".join(sorted(unknown))
                )
            inputs = raw.get("inputs", [])
            if not isinstance(inputs, list) or not all(
                isinstance(item, str) for item in inputs
            ):
                raise ValueError("'inputs' precisa ser uma lista de strings.")
            seats.append(
                Seat(
                    name=str(raw.get("name", "")),
                    connector=str(raw.get("connector", "")),
                    user=str(raw.get("user", "")),
                    inputs=inputs,
                )
            )

        return cls(
            version=int(data.get("version", 1)),
            compositor=str(
                data.get("compositor", "/usr/local/bin/labwc")
            ),
            seats=seats,
        )
