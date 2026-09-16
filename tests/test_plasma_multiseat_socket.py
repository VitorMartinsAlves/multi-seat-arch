import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import plasma_session
from multiseat_arch.runtime_patch_v6 import _wayland_socket_fingerprint


class PlasmaMultiseatSocketTests(unittest.TestCase):
    def test_socket_fingerprint_accepts_real_unix_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wayland-0"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
                fingerprint = _wayland_socket_fingerprint(path)
                self.assertIsNotNone(fingerprint)
                self.assertEqual(len(fingerprint), 2)
            finally:
                server.close()

    def test_session_preserves_launcher_wayland_display(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            socket_path = runtime / "wayland-msa-seat-b"
            socket_path.touch()
            env = {
                "XDG_RUNTIME_DIR": str(runtime),
                "WAYLAND_DISPLAY": "stale-wayland-0",
                "MSA_WAYLAND_DISPLAY": "wayland-msa-seat-b",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertFalse(plasma_session._wayland_socket_ready())
                os.environ["WAYLAND_DISPLAY"] = os.environ["MSA_WAYLAND_DISPLAY"]
                self.assertTrue(plasma_session._wayland_socket_ready())


if __name__ == "__main__":
    unittest.main()
