from __future__ import annotations

import pwd
import shutil
from pathlib import Path
from types import ModuleType


def _labwc_command(compositor: str) -> list[str]:
    command = [compositor]
    if Path(compositor).name == "labwc":
        command.append("--debug")
        session = shutil.which("multi-seat-arch-session")
        if not session:
            raise RuntimeError("multi-seat-arch-session não encontrado; reinstale o pacote.")
        command.extend(["-s", session])
    return command


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_installed", False):
        return

    original_persist = backend._persist_activation_error

    def start_seat(config, seat) -> None:
        account = pwd.getpwnam(seat.user)
        uid = account.pw_uid
        runtime = backend.runtime_seat_name(seat)
        backend._wait_for_lease(seat.connector, uid)

        compositor = (
            config.compositor
            if Path(config.compositor).is_file()
            else backend._resolve_binary(Path(config.compositor).name)
        )
        if not compositor:
            raise RuntimeError(f"Compositor não encontrado: {config.compositor}")

        env = {
            "XDG_SEAT": runtime,
            "DRM_LEASE": seat.connector,
            "XDG_SESSION_TYPE": "wayland",
            "XDG_CURRENT_DESKTOP": "LXQt",
            "XDG_SESSION_DESKTOP": "LXQt",
            "SEATD_VTBOUND": "0",
            "XKB_DEFAULT_LAYOUT": backend._keyboard_layout(),
            "LIBSEAT_BACKEND": "logind",
            "LIBSEAT_LOGLEVEL": "debug",
            "LABWC_UPDATE_ACTIVATION_ENV": "1",
            "QT_QPA_PLATFORM": "wayland;xcb",
            "MOZ_ENABLE_WAYLAND": "1",
        }

        unit = f"msa-seat-{seat.name}"
        backend._systemd_run(
            unit,
            _labwc_command(compositor),
            uid=uid,
            env=env,
            properties=[
                "PAMName=login",
                "UMask=0006",
                "Restart=on-failure",
                "RestartSec=1s",
                "TimeoutStartSec=20s",
                "ExecStartPre=/bin/sleep 0.1",
            ],
        )
        backend._wait_for_wayland(uid, f"{unit}.service")

    def persist_activation_error(exc: BaseException) -> None:
        original_persist(exc)
        try:
            sections: list[str] = []
            commands = [
                ("SEATS", ["loginctl", "list-seats", "--no-legend"]),
                (
                    "MSA UNITS",
                    ["systemctl", "list-units", "--all", "--plain", "--no-legend", "msa-*"],
                ),
            ]
            for title, command in commands:
                result = backend._run(command, check=False)
                sections.append(f"\n--- {title} ---\n{result.stdout.strip()}\n")

            units = backend._list_units(("msa-seat-", "msa-dlm-"))
            for unit in units:
                log = backend._run(
                    ["journalctl", "-u", unit, "-b", "--no-pager", "-o", "cat", "-n", "160"],
                    check=False,
                ).stdout.strip()
                sections.append(f"\n--- {unit} ---\n{log}\n")

            lease_lines: list[str] = []
            for base in backend._lease_runtime_dirs():
                if not base.exists():
                    continue
                for path in sorted(base.iterdir()):
                    try:
                        stat = path.stat()
                        lease_lines.append(
                            f"{path} uid={stat.st_uid} gid={stat.st_gid} mode={oct(stat.st_mode & 0o777)}"
                        )
                    except OSError as error:
                        lease_lines.append(f"{path}: {error}")
            if lease_lines:
                sections.append("\n--- DRM LEASE FILES ---\n" + "\n".join(lease_lines) + "\n")

            with backend.LAST_ERROR.open("a", encoding="utf-8") as handle:
                handle.write("".join(sections))
        except Exception:
            pass

    backend._start_seat = start_seat
    backend._persist_activation_error = persist_activation_error
    backend._msa_runtime_patch_installed = True
