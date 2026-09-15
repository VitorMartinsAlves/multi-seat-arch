import unittest
from unittest.mock import Mock, patch

from multiseat_arch import status


class RuntimeStatusTests(unittest.TestCase):
    def test_parses_active_multiseat_units_from_single_listing(self):
        listing = "\n".join(
            [
                "msa-seat-seat-a.service loaded active running Seat A",
                "msa-seat-seat-b.service loaded failed failed Seat B",
                "msa-input-abc.service loaded active running Input proxy",
                "msa-dlm-card1.service loaded active running DRM lease",
                "unrelated.service loaded active running Something",
            ]
        )
        listed = Mock(returncode=0, stdout=listing)
        hotplug = Mock(returncode=0, stdout="")
        with patch.object(status.subprocess, "run", side_effect=[listed, hotplug]) as run:
            value = status.runtime_status()

        self.assertEqual(value["seats"], ["seat-a"])
        self.assertEqual(value["input_proxies"], ["abc"])
        self.assertEqual(value["drm_cards"], ["card1"])
        self.assertTrue(value["hotplug"])
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
