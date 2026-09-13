from __future__ import annotations

import json
import os
from pathlib import Path

from .model import Config

DEFAULT_PATH = Path("/etc/multi-seat-arch/config.json")


def load(path: str | Path = DEFAULT_PATH) -> Config:
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("A configuração precisa ser um objeto JSON.")
    return Config.from_dict(data)


def save(config: Config, path: str | Path = DEFAULT_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp-{os.getpid()}")
    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False) + "\n"
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.chmod(tmp, 0o644)
        tmp.replace(p)
    finally:
        tmp.unlink(missing_ok=True)
