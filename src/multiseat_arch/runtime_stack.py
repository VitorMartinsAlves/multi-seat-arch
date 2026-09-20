from __future__ import annotations

"""Canonical registration point for the current runtime behavior.

The project historically accumulated compatibility patches while stabilizing
real multiseat hardware. Keeping their order explicit in one place lets us add
regression coverage and fold them into the canonical backend incrementally
without changing the proven execution order in one risky rewrite.
"""

from importlib import import_module
from types import ModuleType

PATCH_MODULES: tuple[str, ...] = (
    "runtime_patch",
    "runtime_patch_v2",
    "runtime_patch_v3",
    "runtime_patch_v4",
    "runtime_patch_v5",
    "runtime_patch_v6",
    "runtime_patch_v7",
    "runtime_patch_v8",
    "runtime_patch_v9",
    "runtime_patch_v10",
    "runtime_patch_v11",
    "runtime_patch_v12",
    "runtime_patch_v13",
    "runtime_patch_v14",
)


def install(backend: ModuleType) -> None:
    """Install the legacy compatibility layers in their established order.

    This function is intentionally behavior-preserving. New runtime work should
    be implemented in canonical modules and removed from this list once tests
    prove that the corresponding compatibility layer is no longer needed.
    """
    if getattr(backend, "_msa_runtime_stack_installed", False):
        return

    for module_name in PATCH_MODULES:
        module = import_module(f"{__package__}.{module_name}")
        installer = getattr(module, "install", None)
        if not callable(installer):
            raise RuntimeError(f"Runtime layer {module_name} has no install()")
        installer(backend)

    backend._msa_runtime_stack_installed = True
