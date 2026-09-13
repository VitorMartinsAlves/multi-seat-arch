import unittest
from unittest.mock import patch

from multiseat_arch import live
from multiseat_arch.model import Config


class LiveSyncTests(unittest.TestCase):
    def test_refuses_sync_when_multiseat_is_not_running(self):
        config = Config()
        with (
            patch.object(live, "runtime_status", return_value={"running": False}),
            patch.object(live, "sync_devices_now") as sync,
        ):
            with self.assertRaises(RuntimeError):
                live.sync_live(config)
            sync.assert_not_called()

    def test_syncs_when_multiseat_is_running(self):
        config = Config()
        with (
            patch.object(live, "runtime_status", return_value={"running": True}),
            patch.object(live, "sync_devices_now") as sync,
        ):
            live.sync_live(config)
            sync.assert_called_once_with(config)


if __name__ == "__main__":
    unittest.main()
