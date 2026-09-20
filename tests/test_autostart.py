import unittest
from unittest.mock import patch

from multiseat_arch import autostart, cli


class AutostartUnitTests(unittest.TestCase):
    def test_boot_unit_has_external_recovery(self):
        text = autostart._autostart_unit_text("/usr/bin/multi-seat-arch")
        self.assertIn("OnFailure=multi-seat-arch-autostart-recovery.service", text)
        self.assertIn("TimeoutStartSec=240", text)
        self.assertIn("ExecStart=/usr/bin/multi-seat-arch _boot", text)

    def test_recovery_unit_uses_separate_process(self):
        text = autostart._recovery_unit_text("/usr/bin/multi-seat-arch")
        self.assertIn("ExecStart=/usr/bin/multi-seat-arch _boot-recover", text)
        self.assertIn("After=multi-seat-arch-autostart.service", text)

    def test_target_does_not_pull_graphical_target(self):
        text = autostart._target_unit_text()
        self.assertIn("Requires=multi-user.target", text)
        self.assertNotIn("graphical.target", text)


class BootRecoveryTests(unittest.TestCase):
    def test_recovery_disables_next_boot_before_restoring_current_boot(self):
        calls: list[str] = []

        with (
            patch.object(
                cli.autostart,
                "disable_after_boot_failure",
                side_effect=lambda: calls.append("disable"),
            ),
            patch.object(cli, "before_restore", side_effect=lambda: calls.append("before")),
            patch.object(cli, "restore_now", side_effect=lambda: calls.append("restore")),
        ):
            cli._recover_failed_boot()

        self.assertEqual(calls, ["disable", "before", "restore"])

    def test_next_boot_is_made_safe_even_if_restore_fails(self):
        with (
            patch.object(cli.autostart, "disable_after_boot_failure") as disable,
            patch.object(cli, "before_restore"),
            patch.object(cli, "restore_now", side_effect=RuntimeError("restore failed")),
        ):
            with self.assertRaisesRegex(RuntimeError, "restore failed"):
                cli._recover_failed_boot()
        disable.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
