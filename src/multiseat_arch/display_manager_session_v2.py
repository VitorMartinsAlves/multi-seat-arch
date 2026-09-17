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
    # Atrium already handed us a live DRM lease fd. Do not propagate the
    # textual lease name into KWin as well: keeping both mechanisms enabled can
    # make KWin try to reacquire the same lease later (notably when XWayland is
    # brought up), which races/fails on secondary seats. The inherited fixed fd
    # is the single source of truth for the compositor lifetime.
    env.pop("KWIN_DRM_LEASE", None)
    env.update(
        {
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
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return parents
    for entry in entries:
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


def _value_after(argv: list[str], option: str) -> str:
    try:
        index = argv.index(option)
    except ValueError:
        return ""
    if index + 1 >= len(argv):
        return ""
    return argv[index + 1]


def _x11_env_from_kwin_wrapper(wrapper_pid: int, timeout: float = 2.0) -> dict[str, str]:
    """Recover this seat's DISPLAY/XAUTHORITY from wrapper-launched KWin.

    kwin_wayland_wrapper allocates the X11 display socket and Xauthority file
    before starting kwin_wayland, then passes both as command-line arguments.
    Reading those arguments is seat-local and does not depend on XWayland being
    spawned yet (Plasma 6 may start XWayland lazily on first X11 client).
    """
    deadline = time.monotonic() + max(timeout, 0.0)
    while True:
        parents = _proc_parent_map()
        for pid in sorted(parents):
            if pid == wrapper_pid or not _is_descendant(pid, wrapper_pid, parents):
                continue
            try:
                raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
            except OSError:
                continue
            argv = [part.decode(errors="ignore") for part in raw.split(b"\0") if part]
            if not argv or Path(argv[0]).name != "kwin_wayland":
                continue
            display = _value_after(argv, "--xwayland-display")
            authority = _value_after(argv, "--xwayland-xauthority")
            result: dict[str, str] = {}
            if display:
                result["DISPLAY"] = display
            if authority:
                result["XAUTHORITY"] = authority
            if result:
                return result
        if time.monotonic() >= deadline:
            return {}
        time.sleep(0.05)


def _restore_user_runtime(env: dict[str, str]) -> None:
    isolated_runtime = Path(env.get("XDG_RUNTIME_DIR", ""))
    display = env.get("WAYLAND_DISPLAY", "")
    if isolated_runtime and display and not os.path.isabs(display):
        env["WAYLAND_DISPLAY"] = str(isolated_runtime / display)

    user_runtime = Path(f"/run/user/{os.getuid()}")
    env["XDG_RUNTIME_DIR"] = str(user_runtime)
    env.pop("PULSE_SERVER", None)


def greeter_main() -> int:
    """Run the distribution's real KDE/SDDM greeter on this leased display.

    Atrium remains the PAM/session backend because it understands our synthetic
    connector seats and hands KWin the DRM lease. The SDDM greeter is only the
    user-facing login UI; sddm_greeter_bridge translates its login request back
    into Atrium's credential/result pipes.
    """
    kwin: subprocess.Popen | None = None
    try:
        kwin, env = _start_kwin(greeter=True)
        from .sddm_greeter_bridge import run_sddm_greeter

        return run_sddm_greeter(env)
    except Exception as exc:
        print(f"multi-seat-arch KDE login greeter: {exc}", file=sys.stderr)
        return 1
    finally:
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

        # The launcher uses kwin_wayland_wrapper. It allocates DISPLAY and
        # XAUTHORITY before XWayland itself starts, so this works with lazy
        # XWayland without adding an artificial startup delay.
        env.update(_x11_env_from_kwin_wrapper(kwin.pid, timeout=2.0))

        _restore_user_runtime(env)
        session = subprocess.Popen([helper], env=env)
        return session.wait()
    except Exception as exc:
        print(f"multi-seat-arch Plasma login session: {exc}", file=sys.stderr)
        return 1
    finally:
        base._terminate(session)
        base._terminate(kwin)
