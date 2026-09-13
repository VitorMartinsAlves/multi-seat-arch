from __future__ import annotations

import os
import pwd
import re
import subprocess

USERNAME_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,30}$")


def validate_username(username: str) -> None:
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Nome de usuário inválido. Use letras minúsculas, números, '_' ou '-', "
            "começando por letra ou '_'."
        )
    try:
        pwd.getpwnam(username)
    except KeyError:
        return
    raise ValueError(f"O usuário '{username}' já existe.")


def create_seat_user(username: str) -> None:
    if os.geteuid() != 0:
        raise PermissionError("Execute como root.")
    validate_username(username)
    proc = subprocess.run(
        ["useradd", "--create-home", "--shell", "/bin/bash", username],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if proc.returncode:
        raise RuntimeError(proc.stdout.strip() or f"useradd falhou ({proc.returncode})")
