from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
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


def _proc_parent_map() -> dict[int, int]:
    parents: dict[int, int] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            for line in (entry / "status").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("PPid:"):
                    parents[int(entry.name)] = int(line.split()[1])
                    break
        except (OSError, ValueError, IndexError):
            continue
    return parents


def _is_descendant(pid: int, ancestor: int, parents: dict[int, int]) -> bool:
    seen: set[int] = set()
    current = pid
    while current > 1 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        current = parents.get(current, 0)
    return False


def _xwayland_env_from_proc(kwin_pid: int, timeout: float = 8.0) -> dict[str, str]:
    """Find the XWayland instance owned by this KWin and recover DISPLAY/auth.

    KWin launches XWayland as a child/descendant. Environment changes made by a
    child process cannot propagate back to this Python launcher, so relying on
    systemd --user to magically contain DISPLAY is racy and often leaves Steam
    and other X11 clients without a display. Reading the matching XWayland
    command line is deterministic per seat and avoids mixing two seats' :N.
    """
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        parents = _proc_parent_map()
        for pid in sorted(parents):
            if not _is_descendant(pid, kwin_pid, parents) or pid == kwin_pid:
                continue
            proc_dir = Path("/proc") / str(pid)
            try:
                raw = (proc_dir / "cmdline").read_bytes()
            except OSError:
                continue
            argv = [part.decode(errors="ignore") for part in raw.split(b"\0") if part]
            if not argv:
                continue
            exe = Path(argv[0]).name.lower()
            if "xwayland" not in exe:
                continue

            display = next((arg for arg in argv[1:] if arg.startswith(":") and arg[1:].isdigit()), "")
            if not display:
                continue

            result = {"DISPLAY": display}
            if "-auth" in argv:
                index = argv.index("-auth")
                if index + 1 < len(argv) and argv[index + 1]:
                    result["XAUTHORITY"] = argv[index + 1]
            return result

        if time.monotonic() >= deadline:
            return {}
        time.sleep(0.1)


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

        # Recover this seat's XWayland DISPLAY/XAUTHORITY directly from the
        # XWayland process launched by this KWin. This is required because a
        # child cannot export environment variables back to this launcher.
        env.update(_xwayland_env_from_proc(kwin.pid, timeout=8.0))

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
