from __future__ import annotations

import grp
import pwd
from types import ModuleType


def install(backend: ModuleType) -> None:
    """Use seatd for compositor device access instead of logind VT ownership.

    The target machine can create real logind seats and both DRM-leased Labwc
    sessions, but logind-backed libseat leaves both compositors without usable
    input because neither service owns an active VT. seatd is designed to broker
    input/display FDs without that active-session restriction; XDG_SEAT/libinput
    still filters each compositor to the ID_SEAT devices created by v2/v3.
    """
    if getattr(backend, "_msa_runtime_patch_v4_installed", False):
        return

    previous_activate = backend.activate_now
    previous_systemd_run = backend._systemd_run

    def ensure_seatd_access(config) -> None:
        if not backend.command_exists("seatd"):
            raise RuntimeError("seatd não encontrado. Instale o pacote seatd.")
        try:
            grp.getgrnam("seat")
        except KeyError as exc:
            raise RuntimeError("Grupo 'seat' não existe; reinstale o pacote seatd.") from exc

        for seat in backend.active_seats(config):
            account = pwd.getpwnam(seat.user)
            groups = {g.gr_name for g in grp.getgrall() if account.pw_name in g.gr_mem}
            primary = grp.getgrgid(account.pw_gid).gr_name
            groups.add(primary)
            if "seat" not in groups:
                result = backend._run(["usermod", "-aG", "seat", account.pw_name], check=False)
                if result.returncode:
                    raise RuntimeError(
                        f"Não foi possível adicionar {account.pw_name} ao grupo seat: {result.stdout.strip()}"
                    )

        backend._run(["systemctl", "start", "seatd.service"], check=False, timeout=15)
        if backend._run(["systemctl", "is-active", "--quiet", "seatd.service"], check=False).returncode != 0:
            log = backend._run(
                ["journalctl", "-u", "seatd.service", "-b", "--no-pager", "-n", "80"],
                check=False,
            ).stdout.strip()
            raise RuntimeError("seatd.service não iniciou." + (f"\n{log}" if log else ""))

    def systemd_run(unit: str, command: list[str], *, uid=None, env=None, properties=None, no_block=False) -> None:
        patched_env = dict(env or {})
        if unit.startswith("msa-seat-"):
            patched_env["LIBSEAT_BACKEND"] = "seatd"
            patched_env["SEATD_VTBOUND"] = "0"
            # Never hide an input-backend failure. If libinput cannot initialize,
            # Labwc must fail so the existing rollback restores graphical.target.
            patched_env.pop("WLR_LIBINPUT_NO_DEVICES", None)
        previous_systemd_run(
            unit,
            command,
            uid=uid,
            env=patched_env,
            properties=properties,
            no_block=no_block,
        )

    def activate(config) -> None:
        ensure_seatd_access(config)
        previous_activate(config)

    backend._systemd_run = systemd_run
    backend.activate_now = activate
    backend._msa_runtime_patch_v4_installed = True
