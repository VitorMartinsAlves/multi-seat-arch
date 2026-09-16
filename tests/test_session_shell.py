import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import runtime_patch, session_shell


class SessionShellTests(unittest.TestCase):
    def test_labwc_command_uses_runtime_config_dir(self):
        command = runtime_patch._labwc_command("/usr/local/bin/labwc", "/run/multi-seat-arch/labwc-seat-a")
        self.assertEqual(command, ["/usr/local/bin/labwc", "--debug", "-C", "/run/multi-seat-arch/labwc-seat-a"])

    def test_prepare_labwc_config_writes_autostart(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "multiseat_arch.runtime_patch.Path", side_effect=lambda value: Path(tmp) / str(value).lstrip("/") if str(value).startswith("/run/multi-seat-arch") else Path(value)
        ), patch("multiseat_arch.runtime_patch.shutil.which", return_value="/usr/bin/multi-seat-arch-session"), patch("multiseat_arch.runtime_patch.os.chown"):
            config = runtime_patch._prepare_labwc_config("seat-a", 1000, 1000)
            autostart = Path(config) / "autostart"
            self.assertTrue(autostart.exists())
            self.assertIn("multi-seat-arch-session", autostart.read_text())

    def test_activation_environment_includes_x11_and_wayland(self):
        calls = []
        env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "XDG_CURRENT_DESKTOP": "LXQt", "XDG_SESSION_TYPE": "wayland"}
        with patch.dict(os.environ, env, clear=True), patch("multiseat_arch.session_shell.shutil.which", return_value="/usr/bin/tool"), patch("multiseat_arch.session_shell._run", side_effect=lambda command: calls.append(command)):
            session_shell._import_activation_environment()
        flattened = " ".join(" ".join(call) for call in calls)
        self.assertIn("WAYLAND_DISPLAY", flattened)
        self.assertIn("DISPLAY", flattened)

    def test_session_shell_uses_app_compat_chromium_strategy(self):
        source = Path(session_shell.__file__).read_text(encoding="utf-8")
        self.assertIn("prefer_xwayland_for_chromium", source)
        self.assertNotIn("_ensure_chromium_wayland_flags", source)


if __name__ == "__main__":
    unittest.main()
