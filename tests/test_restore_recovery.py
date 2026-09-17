import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from multiseat_arch.runtime_patch_v13 import _restart_display_manager
from multiseat_arch.runtime_patch_v14 import _multiseat_users


def completed(args, returncode=0, stdout=""):
    return subprocess.CompletedProcess(args, returncode, stdout, "")


class RestoreRecoveryTests(unittest.TestCase):
    def test_multiseat_user_detection_ignores_seat0(self):
        backend = SimpleNamespace()
        backend._run = Mock(
            return_value=completed(
                ["loginctl"],
                stdout=(
                    "10 1000 alice seat-card1-HDMI-A-1 tty2\n"
                    "11 1001 bob seat-card1-eDP-1 tty3\n"
                    "12 1000 alice seat0 tty1\n"
                ),
            )
        )
        self.assertEqual(_multiseat_users(backend), ["alice", "bob"])

    def test_display_manager_restart_prefers_alias(self):
        backend = SimpleNamespace()
        calls = []

        def run(args, **_kwargs):
            calls.append(args)
            if args[:3] == ["systemctl", "is-active", "--quiet"]:
                return completed(args, returncode=0)
            return completed(args)

        backend._run = run
        _restart_display_manager(backend)

        self.assertIn(["systemctl", "start", "graphical.target"], calls)
        self.assertIn(["systemctl", "restart", "display-manager.service"], calls)
        self.assertNotIn(["systemctl", "restart", "sddm.service"], calls)

    def test_display_manager_restart_falls_back_to_sddm(self):
        backend = SimpleNamespace()
        calls = []

        def run(args, **_kwargs):
            calls.append(args)
            if args == ["systemctl", "restart", "display-manager.service"]:
                return completed(args, returncode=1)
            if args[:3] == ["systemctl", "is-active", "--quiet"]:
                return completed(args, returncode=0)
            return completed(args)

        backend._run = run
        _restart_display_manager(backend)
        self.assertIn(["systemctl", "restart", "sddm.service"], calls)


if __name__ == "__main__":
    unittest.main()
