from __future__ import annotations

import json
from pathlib import Path
from .model import Config

DEFAULT_PATH = Path("/etc/multi-seat-arch/config.json")

def load(path: str | Path = DEFAULT_PATH) -> Config:
    p = Path(path)
    return Config.from_dict(json.loads(p.read_text(encoding="utf-8")))

def save(config: Config, path: str | Path = DEFAULT_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(p)
