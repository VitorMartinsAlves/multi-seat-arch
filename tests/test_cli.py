from contextlib import nullcontext
import unittest
from unittest.mock import patch

from multiseat_arch import cli
from multiseat_arch.model import Config, Seat


class CliTransactionTests(unittest.TestCase):
    def test_apply_sync_rolls_back_previous_config(self):
        previous = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "alice")])
        new = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "alice")])

        with (
            patch.object(cli, "ensure_multiseat_running"),
            patch.object(cli, "input_sync_lock", return_value=nullcontext()),
            patch.object(cli, "_installed_config_or_none", return_value=previous),
            patch.object(cli.cfg, "save") as save,
            patch.object(
                cli,
                "sync_devices_now",
                side_effect=[RuntimeError("new failed"), None],
            ) as sync,
        ):
            with self.assertRaisesRegex(RuntimeError, "foram restauradas"):
                cli._apply_sync_transaction(new)

            self.assertEqual(save.call_args_list[0].args, (new,))
            self.assertEqual(save.call_args_list[1].args, (previous,))
            self.assertEqual(sync.call_args_list[0].args, (new,))
            self.assertEqual(sync.call_args_list[1].args, (previous,))

    def test_apply_sync_reports_double_failure(self):
        previous = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "alice")])
        new = Config(seats=[Seat("seat-a", "card1-HDMI-A-1", "alice")])

        with (
            patch.object(cli, "ensure_multiseat_running"),
            patch.object(cli, "input_sync_lock", return_value=nullcontext()),
            patch.object(cli, "_installed_config_or_none", return_value=previous),
            patch.object(cli.cfg, "save"),
            patch.object(
                cli,
                "sync_devices_now",
                side_effect=[RuntimeError("new failed"), RuntimeError("rollback failed")],
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "rollback também falhou"):
                cli._apply_sync_transaction(new)


if __name__ == "__main__":
    unittest.main()
