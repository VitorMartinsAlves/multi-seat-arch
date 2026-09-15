import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import plasma_session
from multiseat_arch.runtime_patch_v6 import _socket_name


class PlasmaMultiseatSocketTests(unittest.TestCase):
    def test_socket_name_is_stable_per_seat(self):
        self.assertEqual(_socket_name("seat-a"), "wayland-msa-seat-a")
        self.assertEqual(_socket_name("seat-b"), "wayland-msa-seat-b")
        self.assertNotEqual(_socket_name("seat-a"), _socket_name("seat-b"))

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
                self.assertTrue(plasma_session._wayland_socket_ready() is False)
                os.environ["WAYLAND_DISPLAY"] = os.environ["MSA_WAYLAND_DISPLAY"]
                self.assertTrue(plasma_session._wayland_socket_ready())


if __name__ == "__main__":
    unittest.main()
