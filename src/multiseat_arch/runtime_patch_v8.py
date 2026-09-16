from __future__ import annotations

from types import ModuleType

from . import dynamic_login

_FIXED_USER_ERROR_PREFIXES = (
    "Usuário de sistema/root não pode ser usado no seat:",
    "Usuário inexistente:",
    "Use usuários diferentes por seat para evitar conflito",
)


def _drop_fixed_user_errors(errors: list[str]) -> list[str]:
    """Remove validation that only belongs to the legacy fixed-user backend.

    In the Atrium login-manager backend a seat represents hardware (display +
    inputs), not an account. Authentication happens later in the greeter, so a
    persisted Seat.user value is legacy metadata and must not constrain which
    account can use that seat.
    """
    return [
        error
        for error in errors
        if not error.startswith(_FIXED_USER_ERROR_PREFIXES)
    ]


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v8_installed", False):
        return

    previous_validate = backend.validate
    previous_activate = backend.activate_now

    def validate(config) -> list[str]:
        # This experimental Plasma branch is display-bound, not user-bound.
        # Keep reading the legacy `user` field for config compatibility, but do
        # not let it participate in validation or runtime ownership.
        return _drop_fixed_user_errors(previous_validate(config))

    def activate(config) -> None:
        # Dynamic login is the normal lifecycle for this branch. Enabling it at
        # activation time makes GUI/CLI starts deterministic and prevents a
        # silent fallback to the old per-seat fixed-user compositor path.
        if not dynamic_login.enabled():
            dynamic_login.enable()
        previous_activate(config)

    backend.validate = validate
    backend.activate_now = activate
    backend._msa_runtime_patch_v8_installed = True
