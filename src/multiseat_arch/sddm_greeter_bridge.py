from __future__ import annotations

import configparser
import os
import shutil
import socket
import subprocess
from pathlib import Path

from PyQt6.QtCore import QCoreApplication, QDataStream, QSocketNotifier, QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

# SDDM src/common/Messages.h. Keep the wire values explicit so the stock
# sddm-greeter can be used unchanged while Atrium remains the PAM/session
# backend that owns our synthetic DRM seats.
GREETER_CONNECT = 0
GREETER_LOGIN = 1
GREETER_POWER_OFF = 2
GREETER_REBOOT = 3
GREETER_SUSPEND = 4
GREETER_HIBERNATE = 5
GREETER_HYBRID_SLEEP = 6

DAEMON_HOST_NAME = 0
DAEMON_CAPABILITIES = 1
DAEMON_LOGIN_SUCCEEDED = 2
DAEMON_LOGIN_FAILED = 3
DAEMON_INFORMATION = 4

CAP_POWER_OFF = 0x0001
CAP_REBOOT = 0x0002
CAP_SUSPEND = 0x0004
CAP_HIBERNATE = 0x0008
CAP_HYBRID_SLEEP = 0x0010


def find_sddm_greeter() -> str:
    for candidate in (
        "sddm-greeter-qt6",
        "sddm-greeter",
        "/usr/lib/sddm/sddm-greeter-qt6",
        "/usr/lib/sddm/sddm-greeter",
    ):
        found = shutil.which(candidate) if not candidate.startswith("/") else candidate
        if found and Path(found).is_file() and os.access(found, os.X_OK):
            return str(Path(found).resolve())
    raise RuntimeError("Greeter do SDDM não encontrado. Instale o pacote sddm.")


def _sddm_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    paths: list[Path] = []
    for root in (Path("/usr/lib/sddm/sddm.conf.d"), Path("/etc/sddm.conf.d")):
        if root.is_dir():
            paths.extend(sorted(root.glob("*.conf")))
    paths.append(Path("/etc/sddm.conf"))
    parser.read([str(path) for path in paths if path.is_file()], encoding="utf-8")
    return parser


def find_sddm_theme() -> str:
    parser = _sddm_config()
    current = parser.get("Theme", "Current", fallback="").strip()
    candidates = [current, "breeze"] if current else ["breeze"]
    theme_root = Path("/usr/share/sddm/themes")
    for name in candidates:
        if not name:
            continue
        path = theme_root / name
        if (path / "Main.qml").is_file():
            return str(path)
    if theme_root.is_dir():
        for path in sorted(theme_root.iterdir()):
            if (path / "Main.qml").is_file():
                return str(path)
    raise RuntimeError("Nenhum tema SDDM instalado; o tema Breeze do KDE é necessário.")


def _atrium_session_id() -> str:
    preferred = os.environ.get("ATRIUM_SESSION_PRESELECT", "").strip()
    if preferred:
        return preferred

    raw = os.environ.get("ATRIUM_SESSION_LIST", "")
    first = ""
    plasma = ""
    for record in raw.split("\x1e"):
        if "\x1f" not in record:
            continue
        session_id, name = record.split("\x1f", 1)
        session_id = session_id.strip()
        if not session_id:
            continue
        if not first:
            first = session_id
        marker = f"{session_id} {name}".lower()
        if "plasma" in marker or "kde" in marker:
            plasma = session_id
            break
    return plasma or first


def _fd_from_env(name: str) -> int:
    value = os.environ.get(name, "")
    try:
        fd = int(value)
        os.fstat(fd)
    except (ValueError, OSError) as exc:
        raise RuntimeError(f"{name} inválido/ausente no greeter multiseat.") from exc
    return fd


class SddmAtriumBridge:
    """Minimal SDDM daemon endpoint backed by Atrium's credential pipes.

    The visual process is the distribution's real sddm-greeter and therefore
    loads the same KDE/SDDM theme, user model, faces and keyboard UI used by the
    normal host login screen. Only the authentication transport is translated:
    SDDM's Login message is forwarded to Atrium, which keeps PAM and the DRM
    seat lifecycle authoritative.
    """

    def __init__(self, env: dict[str, str]):
        self.env = env
        self.credentials_fd = _fd_from_env("CREDENTIALS_FD")
        self.result_fd = _fd_from_env("RESULT_FD")
        self.session_id = _atrium_session_id()
        self.server = QLocalServer()
        self.client: QLocalSocket | None = None
        self.child: subprocess.Popen | None = None
        self.pending_login = False
        self.exit_code = 1

        runtime = Path(env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}")
        runtime.mkdir(parents=True, exist_ok=True)
        self.socket_path = runtime / f"msa-sddm-greeter-{os.getpid()}.sock"
        QLocalServer.removeServer(str(self.socket_path))
        if not self.server.listen(str(self.socket_path)):
            raise RuntimeError(f"Não foi possível criar socket do greeter SDDM: {self.server.errorString()}")
        self.server.newConnection.connect(self._accept)

        self.result_notifier = QSocketNotifier(self.result_fd, QSocketNotifier.Type.Read)
        self.result_notifier.setEnabled(False)
        self.result_notifier.activated.connect(self._read_atrium_result)

        self.poll_timer = QTimer()
        self.poll_timer.setInterval(250)
        self.poll_timer.timeout.connect(self._poll_child)

    def start(self) -> int:
        greeter = find_sddm_greeter()
        theme = find_sddm_theme()
        child_env = self.env.copy()
        child_env["QT_QPA_PLATFORM"] = "wayland"
        child_env.setdefault("XDG_CURRENT_DESKTOP", "KDE")
        child_env.setdefault("XDG_SESSION_DESKTOP", "KDE")

        # The stock SDDM greeter uses this socket exactly as it would use the
        # real SDDM daemon. Its own UserModel enumerates local users, so the user
        # chooser remains dynamic and does not belong to a particular seat.
        self.child = subprocess.Popen(
            [greeter, "--socket", str(self.socket_path), "--theme", theme],
            env=child_env,
        )
        self.poll_timer.start()
        return QCoreApplication.instance().exec()

    def close(self) -> None:
        self.result_notifier.setEnabled(False)
        self.server.close()
        QLocalServer.removeServer(str(self.socket_path))
        if self.child is not None and self.child.poll() is None:
            self.child.terminate()
            try:
                self.child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.child.kill()
                self.child.wait(timeout=2)

    def _accept(self) -> None:
        if self.client is not None:
            extra = self.server.nextPendingConnection()
            if extra is not None:
                extra.close()
            return
        self.client = self.server.nextPendingConnection()
        if self.client is None:
            return
        self.client.readyRead.connect(self._read_sddm)
        self.client.disconnected.connect(self._client_disconnected)

    def _send_u32(self, value: int) -> None:
        if self.client is None:
            return
        stream = QDataStream(self.client)
        stream.writeUInt32(value)
        self.client.flush()

    def _send_capabilities(self) -> None:
        if self.client is None:
            return
        # Power actions are intentionally not advertised yet. Authentication
        # and user switching are seat-local; machine power actions are global.
        stream = QDataStream(self.client)
        stream.writeUInt32(DAEMON_CAPABILITIES)
        stream.writeUInt32(0)
        stream.writeUInt32(DAEMON_HOST_NAME)
        stream.writeQString(socket.gethostname())
        self.client.flush()

    def _read_sddm(self) -> None:
        if self.client is None:
            return
        stream = QDataStream(self.client)
        while self.client.bytesAvailable() >= 4:
            stream.startTransaction()
            message = stream.readUInt32()
            if message == GREETER_LOGIN:
                username = stream.readQString()
                password = stream.readQString()
                _session_type = stream.readUInt32()
                _session_file = stream.readQString()
                if not stream.commitTransaction():
                    return
                self._login(username, password)
                continue
            if not stream.commitTransaction():
                return

            if message == GREETER_CONNECT:
                self._send_capabilities()
            elif message in {
                GREETER_POWER_OFF,
                GREETER_REBOOT,
                GREETER_SUSPEND,
                GREETER_HIBERNATE,
                GREETER_HYBRID_SLEEP,
            }:
                # Not advertised, but ignore gracefully if a custom theme calls
                # one of these methods anyway.
                continue

    def _login(self, username: str, password: str) -> None:
        if self.pending_login:
            return
        if not username:
            self._send_u32(DAEMON_LOGIN_FAILED)
            return

        session_id = self.session_id
        if not session_id:
            # Atrium accepts an empty session id as its configured/default
            # desktop on current builds, but keep the field explicit.
            session_id = ""
        payload = (
            username.encode("utf-8", "surrogateescape")
            + b"\0"
            + password.encode("utf-8", "surrogateescape")
            + b"\0"
            + session_id.encode("utf-8", "surrogateescape")
            + b"\0"
        )
        try:
            os.write(self.credentials_fd, payload)
        except OSError:
            self._send_u32(DAEMON_LOGIN_FAILED)
            return
        self.pending_login = True
        self.result_notifier.setEnabled(True)

    def _read_atrium_result(self, _fd: int) -> None:
        try:
            result = os.read(self.result_fd, 4096)
        except OSError:
            result = b""
        self.result_notifier.setEnabled(False)
        self.pending_login = False

        if result == b"ok\n" or result.startswith(b"ok\n"):
            self.exit_code = 0
            self._send_u32(DAEMON_LOGIN_SUCCEEDED)
            # Give QLocalSocket a chance to flush the success message before the
            # wrapper tears down the greeter KWin and Atrium starts the session.
            QTimer.singleShot(120, QCoreApplication.instance().quit)
            return

        self._send_u32(DAEMON_LOGIN_FAILED)

    def _client_disconnected(self) -> None:
        if self.exit_code != 0:
            QCoreApplication.instance().quit()

    def _poll_child(self) -> None:
        if self.child is None:
            return
        code = self.child.poll()
        if code is None:
            return
        if self.exit_code != 0:
            self.exit_code = code if code != 0 else 1
        QCoreApplication.instance().quit()


def run_sddm_greeter(env: dict[str, str]) -> int:
    app = QCoreApplication.instance() or QCoreApplication([])
    bridge = SddmAtriumBridge(env)
    try:
        bridge.start()
        return bridge.exit_code
    finally:
        bridge.close()
