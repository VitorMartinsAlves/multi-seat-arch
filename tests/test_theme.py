import tempfile
import unittest
from pathlib import Path

from multiseat_arch import theme


class ThemeTests(unittest.TestCase):
    def test_theme_is_seeded_once_and_existing_panel_is_backed_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            panel = home / ".config/lxqt/panel.conf"
            panel.parent.mkdir(parents=True)
            panel.write_text("old-panel\n", encoding="utf-8")

            changed = theme.apply_kde_like_theme(home)
            self.assertTrue(changed)
            self.assertEqual(
                (home / ".config/lxqt/panel.conf.msa-backup").read_text(encoding="utf-8"),
                "old-panel\n",
            )
            seeded = panel.read_text(encoding="utf-8")
            self.assertIn("position=Bottom", seeded)
            self.assertIn("plugins=mainmenu,quicklaunch,taskbar", seeded)
            self.assertEqual(
                (home / ".config/multi-seat-arch/theme-version").read_text(encoding="utf-8").strip(),
                theme.THEME_VERSION,
            )

            panel.write_text("user-customized\n", encoding="utf-8")
            changed_again = theme.apply_kde_like_theme(home)
            self.assertFalse(changed_again)
            self.assertEqual(panel.read_text(encoding="utf-8"), "user-customized\n")

    def test_lxqt_profile_uses_breeze_visuals(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            theme.apply_kde_like_theme(home)
            text = (home / ".config/lxqt/lxqt.conf").read_text(encoding="utf-8")
            self.assertIn("icon_theme=breeze-dark", text)
            self.assertIn("style=Breeze", text)
            self.assertIn("highlight_color=#3daee9", text)


if __name__ == "__main__":
    unittest.main()
