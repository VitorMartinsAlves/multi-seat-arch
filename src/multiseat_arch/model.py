from __future__ import annotations

from dataclasses import dataclass, field, asdict
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
            "seats": [asdict(s) for s in self.seats],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        return cls(
            version=int(data.get("version", 1)),
            compositor=str(data.get("compositor", "/usr/local/bin/labwc")),
            seats=[Seat(**seat) for seat in data.get("seats", [])],
        )
