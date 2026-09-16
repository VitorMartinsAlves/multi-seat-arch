from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import display_manager_session as base

KWIN_FIXED_LEASE_FD = 198


def _start_kwin(*, greeter: bool) -> tuple[subprocess.Popen, dict[str, str]]:
    if not Path(base.KWIN).is_file():
        raise RuntimeError("KWin experimental ausente; rode scripts/build-kwin-plasma.sh.")

    connector = base._connector_from_seat()
    lease_fd = base._lease_fd()
    card = connector.split("-", 1)[0]
    runtime = base._runtime_dir()
    before = base._snapshot(runtime)

    env = os.environ.copy()
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    env.pop("XAUTHORITY", None)
    env.update(
        {
            "KWIN_DRM_LEASE": connector,
            "KWIN_DRM_LEASE_FD": str(KWIN_FIXED_LEASE_FD),
            "KWIN_DRM_DEVICES": f"/dev/dri/{card}",
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_SESSION_TYPE": "wayland",
            "QT_QPA_PLATFORM": "wayland",
            "MOZ_ENABLE_WAYLAND": "1",
        }
    )
    if greeter:
        env["XDG_CURRENT_DESKTOP"] = "KDE"
        env["XDG_SESSION_DESKTOP"] = "KDE"

    args = [base.KWIN]
    if greeter:
        args.extend(["--no-lockscreen", "--no-global-shortcuts"])

    duplicated = lease_fd != KWIN_FIXED_LEASE_FD
    if duplicated:
        os.dup2(lease_fd, KWIN_FIXED_LEASE_FD, inheritable=True)
    else:
        os.set_inheritable(KWIN_FIXED_LEASE_FD, True)

    try:
        proc = subprocess.Popen(
            args,
            env=env,
            pass_fds=(KWIN_FIXED_LEASE_FD,),
        )
    finally:
        if duplicated:
            try:
                os.close(KWIN_FIXED_LEASE_FD)
            except OSError:
                pass

    display = base._wait_new_socket(runtime, before, proc)
    client_env = env.copy()
    client_env["WAYLAND_DISPLAY"] = display
    return proc, client_env


def _restore_user_runtime(env: dict[str, str]) -> None:
    """Keep the seat-specific Wayland socket while restoring the user's runtime.

    KWin needs an isolated XDG_RUNTIME_DIR so two compositors owned by the same
    login user do not race for wayland-0. Plasma applications, however, must use
    /run/user/<uid> for the user bus, PipeWire and pipewire-pulse sockets.

    WAYLAND_DISPLAY accepts an absolute socket path, so point it at KWin's
    isolated socket before switching XDG_RUNTIME_DIR back to the normal user
    runtime directory.
    """
    isolated_runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    display = env.get("WAYLAND_DISPLAY", "")
    if isolated_runtime and display and not os.path.isabs(display):
        env["WAYLAND_DISPLAY"] = str(isolated_runtime / display)

    user_runtime = Path(f"/run/user/{os.getuid()}")
    env["XDG_RUNTIME_DIR"] = str(user_runtime)

    # Do not carry a stale Pulse override from the greeter environment. Pulse
    # compatibility will then resolve to /run/user/<uid>/pulse/native normally.
    env.pop("PULSE_SERVER", None)


def greeter_main() -> int:
    kwin: subprocess.Popen | None = None
    child: subprocess.Popen | None = None
    try:
        kwin, env = _start_kwin(greeter=True)
        greeter = next((path for path in base.ATRIUM_GREETER_CANDIDATES if Path(path).is_file()), None)
        if greeter is None:
            raise RuntimeError("atrium-gtk-greeter não encontrado.")
        fds = base._passthrough_fds("CREDENTIALS_FD", "RESULT_FD")
        child = subprocess.Popen([greeter], env=env, pass_fds=fds)
        return child.wait()
    except Exception as exc:
        print(f"multi-seat-arch login greeter: {exc}", file=sys.stderr)
        return 1
    finally:
        base._terminate(child)
        base._terminate(kwin)


def plasma_main() -> int:
    kwin: subprocess.Popen | None = None
    session: subprocess.Popen | None = None
    try:
        kwin, env = _start_kwin(greeter=False)
        helper = shutil.which("multi-seat-arch-plasma-session")
        if not helper:
            raise RuntimeError("multi-seat-arch-plasma-session não encontrado.")
        env.update(
            {
                "XDG_CURRENT_DESKTOP": "KDE",
                "XDG_SESSION_DESKTOP": "KDE",
                "KDE_FULL_SESSION": "true",
                "KDE_SESSION_VERSION": "6",
            }
        )
        env.pop("KWIN_DRM_LEASE_FD", None)
        env.pop("KWIN_DRM_LEASE", None)
        env.pop("KWIN_DRM_DEVICES", None)

        # Only KWin stays on the isolated per-seat runtime. Restore the normal
        # user runtime for Plasma so DBus, PipeWire and Pulse sockets resolve.
        _restore_user_runtime(env)

        session = subprocess.Popen([helper], env=env)
        return session.wait()
    except Exception as exc:
        print(f"multi-seat-arch Plasma login session: {exc}", file=sys.stderr)
        return 1
    finally:
        base._terminate(session)
        base._terminate(kwin)
