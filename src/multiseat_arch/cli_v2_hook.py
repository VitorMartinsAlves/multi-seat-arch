from __future__ import annotations

from .runtime_patch_v2 import install


def apply(backend) -> None:
    install(backend)
