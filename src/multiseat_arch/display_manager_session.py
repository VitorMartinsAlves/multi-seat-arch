from __future__ import annotations

import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

KWIN = "/usr/local/bin/kwin-wayland-msa"
ATRIUM_GREETER_CANDIDATES = (
    "/usr/lib/atrium/atrium-gtk-greeter",
    "/usr/local/lib/atrium/atrium-gtk-greeter",
)


def _connector_from_seat() -> str:
    seat = os.environ.get("XDG_SEAT", "")
    if not seat.startswith("seat-"):
        raise RuntimeError(f"XDG_SEAT inválido para seat DRM: {seat or '<vazio>'}")
    connector = seat.removeprefix("seat-")
    if not connector.startswith("card") or "-" not in connector:
        raise RuntimeError(f"Seat não corresponde a um conector DRM: {seat}")
    return connector


def _lease_fd() -> int:
    value = os.environ.get("KWIN_DRM_LEASE_FD", "")
    try:
        fd = int(value)
    except ValueError as exc:
        raise RuntimeError("KWIN_DRM_LEASE_FD não foi fornecido pelo login manager.") from exc
    if fd < 0:
        raise RuntimeError("KWIN_DRM_LEASE_FD inválido.")
    try:
        os.fstat(fd)
    except OSError as exc:
        raise RuntimeError(f"DRM lease fd {fd} não está aberto: {exc}") from exc
    return fd


def _runtime_dir() -> Path:
    path = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _socket_fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    if not path.is_socket():
        return None
    return (st.st_ino, st.st_mtime_ns)


def _snapshot(runtime: Path) -> dict[str, tuple[int, int]]:
    result: dict[str, tuple[int, int]] = {}
    for path in runtime.glob("wayland-*"):
        if path.name.endswith(".lock"):
            continue
        fp = _socket_fingerprint(path)
        if fp is not None:
            result[path.name] = fp
    return result


def _connectable(path: Path) -> bool:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.2)
    try:
        client.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        client.close()


def _wait_new_socket(runtime: Path, before: dict[str, tuple[int, int]], proc: subprocess.Popen, timeout: float = 25.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"KWin encerrou antes de criar o socket Wayland (status {proc.returncode}).")
        for path in sorted(runtime.glob("wayland-*")):
            if path.name.endswith(".lock"):
                continue
            fp = _socket_fingerprint(path)
            if fp is None or before.get(path.name) == fp:
                continue
            if _connectable(path):
                return path.name
        time.sleep(0.1)
    raise RuntimeError("KWin não publicou um socket Wayland novo em 25s.")


def _terminate(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)


def _start_kwin(*, greeter: bool) -> tuple[subprocess.Popen, dict[str, str]]:
    if not Path(KWIN).is_file():
        raise RuntimeError("KWin experimental ausente; rode scripts/build-kwin-plasma.sh.")

    connector = _connector_from_seat()
    lease_fd = _lease_fd()
    card = connector.split("-", 1)[0]
    runtime = _runtime_dir()
    before = _snapshot(runtime)

    env = os.environ.copy()
    env.pop("WAYLAND_DISPLAY", None)
    env.pop("DISPLAY", None)
    env.pop("XAUTHORITY", None)
    env.update(
        {
            "KWIN_DRM_LEASE": connector,
            "KWIN_DRM_LEASE_FD": str(lease_fd),
            "KWIN_DRM_DEVICES": f"/dev/dri/{card}",
            "XDG_SESSION_TYPE": "wayland",
            "QT_QPA_PLATFORM": "wayland",
            "MOZ_ENABLE_WAYLAND": "1",
        }
    )
    if greeter:
        env["XDG_CURRENT_DESKTOP"] = "KDE"
        env["XDG_SESSION_DESKTOP"] = "KDE"

    args = [KWIN]
    if greeter:
        args.extend(["--no-lockscreen", "--no-global-shortcuts"])

    proc = subprocess.Popen(args, env=env, pass_fds=(lease_fd,))
    display = _wait_new_socket(runtime, before, proc)
    client_env = env.copy()
    client_env["WAYLAND_DISPLAY"] = display
    return proc, client_env


def _passthrough_fds(*names: str) -> tuple[int, ...]:
    result: list[int] = []
    for name in names:
        value = os.environ.get(name, "")
        if not value:
            continue
        try:
            fd = int(value)
            os.fstat(fd)
        except (ValueError, OSError):
            continue
        result.append(fd)
    return tuple(result)


def greeter_main() -> int:
    kwin: subprocess.Popen | None = None
    child: subprocess.Popen | None = None
    try:
        kwin, env = _start_kwin(greeter=True)
        greeter = next((path for path in ATRIUM_GREETER_CANDIDATES if Path(path).is_file()), None)
        if greeter is None:
            raise RuntimeError("atrium-gtk-greeter não encontrado.")
        fds = _passthrough_fds("CREDENTIALS_FD", "RESULT_FD")
        child = subprocess.Popen([greeter], env=env, pass_fds=fds)
        return child.wait()
    except Exception as exc:
        print(f"multi-seat-arch login greeter: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate(child)
        _terminate(kwin)


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
        # The Plasma helper must not get the DRM lease fd; only KWin owns it.
        env.pop("KWIN_DRM_LEASE_FD", None)
        env.pop("KWIN_DRM_LEASE", None)
        env.pop("KWIN_DRM_DEVICES", None)
        session = subprocess.Popen([helper], env=env)
        return session.wait()
    except Exception as exc:
        print(f"multi-seat-arch Plasma login session: {exc}", file=sys.stderr)
        return 1
    finally:
        _terminate(session)
        _terminate(kwin)


if __name__ == "__main__":
    mode = Path(sys.argv[0]).name
    raise SystemExit(greeter_main() if "greeter" in mode else plasma_main())
