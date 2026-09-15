import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import runtime_patch, session_shell


class SessionShellTests(unittest.TestCase):
    def test_labwc_command_starts_session_helper(self):
        with patch("multiseat_arch.runtime_patch.shutil.which", return_value="/usr/bin/multi-seat-arch-session"):
            command = runtime_patch._labwc_command("/usr/local/bin/labwc")
        self.assertEqual(
            command,
            ["/usr/local/bin/labwc", "--debug", "-s", "/usr/bin/multi-seat-arch-session"],
        )

    def test_labwc_command_fails_if_session_helper_is_missing(self):
        with patch("multiseat_arch.runtime_patch.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "multi-seat-arch-session"):
                runtime_patch._labwc_command("/usr/local/bin/labwc")

    def test_plasma_wallpaper_is_reused_for_both_pcmanfm_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            wallpaper = home / "wall paper.jpg"
            wallpaper.write_bytes(b"fake")
            plasma = home / ".config/plasma-org.kde.plasma.desktop-appletsrc"
            plasma.parent.mkdir(parents=True)
            encoded = str(wallpaper).replace(" ", "%20")
            plasma.write_text(f"[Wallpaper]\nImage=file://{encoded}\n", encoding="utf-8")

            with patch("multiseat_arch.session_shell.Path.home", return_value=home):
                session_shell._prepare_pcmanfm_profiles()

            for profile_name in ("lxqt", "lxqtwayland"):
                settings = home / f".config/pcmanfm-qt/{profile_name}/settings.conf"
                text = settings.read_text(encoding="utf-8")
                self.assertIn(f"Wallpaper={wallpaper}", text)
                self.assertIn("WallpaperMode=zoom", text)

    def test_existing_valid_wallpaper_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            existing = home / "custom.jpg"
            existing.write_bytes(b"custom")
            profile = home / ".config/pcmanfm-qt/lxqt/settings.conf"
            profile.parent.mkdir(parents=True)
            profile.write_text(f"[Desktop]\nWallpaper={existing}\nWallpaperMode=fit\n", encoding="utf-8")

            with patch("multiseat_arch.session_shell.Path.home", return_value=home):
                session_shell._prepare_pcmanfm_profile("lxqt", "/other/wallpaper.jpg")

            text = profile.read_text(encoding="utf-8")
            self.assertIn(f"Wallpaper={existing}", text)
            self.assertIn("WallpaperMode=fit", text)

    def test_activation_environment_includes_x11_and_wayland(self):
        calls = []

        def record(command):
            calls.append(command)

        env = {
            "WAYLAND_DISPLAY": "wayland-0",
            "DISPLAY": ":0",
            "XDG_CURRENT_DESKTOP": "LXQt",
            "XDG_SESSION_TYPE": "wayland",
        }
        with patch.dict(os.environ, env, clear=True), patch(
            "multiseat_arch.session_shell.shutil.which", return_value="/usr/bin/tool"
        ), patch("multiseat_arch.session_shell._run", side_effect=record):
            session_shell._import_activation_environment()

        flattened = " ".join(" ".join(call) for call in calls)
        self.assertIn("WAYLAND_DISPLAY", flattened)
        self.assertIn("DISPLAY", flattened)


if __name__ == "__main__":
    unittest.main()
