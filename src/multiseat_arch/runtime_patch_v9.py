from __future__ import annotations

import subprocess
from types import ModuleType


def install(backend: ModuleType) -> None:
    if getattr(backend, "_msa_runtime_patch_v9_installed", False):
        return

    previous_activate = backend.activate_now

    def activate(config) -> None:
        original_run = backend._run

        def safe_run(cmd: list[str], check: bool = True, timeout: float | None = None):
            # Do not isolate multi-user.target here. The activation helper itself
            # is a transient systemd service, and an isolate can kill the
            # control path that is supposed to start Atrium and perform rollback.
            # Stopping only the host display manager is sufficient to release
            # the normal KWin/SDDM DRM master while keeping msa-activate alive.
            if cmd == ["systemctl", "isolate", "multi-user.target"]:
                result = original_run(
                    ["systemctl", "stop", "display-manager.service"],
                    check=False,
                    timeout=timeout,
                )
                if result.returncode != 0 and check:
                    raise subprocess.CalledProcessError(
                        result.returncode,
                        cmd,
                        output=result.stdout,
                    )
                return subprocess.CompletedProcess(cmd, result.returncode, result.stdout)
            return original_run(cmd, check=check, timeout=timeout)

        backend._run = safe_run
        try:
            previous_activate(config)
        finally:
            backend._run = original_run

    backend.activate_now = activate
    backend._msa_runtime_patch_v9_installed = True
