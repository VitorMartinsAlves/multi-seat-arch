import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import app_compat


class AppCompatTests(unittest.TestCase):
    def test_chromium_cleanup_removes_only_project_ozone_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            cfg = home / ".config/chrome-flags.conf"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                "--disable-gpu\n--ozone-platform-hint=auto\n--enable-features=UseOzonePlatform\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OZONE_PLATFORM": "wayland", "NIXOS_OZONE_WL": "1"}, clear=False):
                app_compat.prefer_xwayland_for_chromium(home)
                self.assertNotIn("OZONE_PLATFORM", os.environ)
                self.assertNotIn("NIXOS_OZONE_WL", os.environ)
            text = cfg.read_text(encoding="utf-8")
            self.assertIn("--disable-gpu", text)
            self.assertNotIn("ozone-platform", text)
            self.assertNotIn("UseOzonePlatform", text)

    def test_session_launcher_uses_lxqt_leave(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            "multiseat_arch.app_compat.shutil.which", return_value="/usr/bin/lxqt-leave"
        ):
            path = app_compat.create_session_launcher(Path(tmp))
            text = path.read_text(encoding="utf-8")
            self.assertIn("Name=Sessão", text)
            self.assertIn("Exec=/usr/bin/lxqt-leave", text)
            self.assertIn("Icon=system-shutdown", text)


if __name__ == "__main__":
    unittest.main()
