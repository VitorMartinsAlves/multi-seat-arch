import os
import unittest
from unittest.mock import patch

from multiseat_arch import sddm_greeter_bridge as bridge


class SddmGreeterBridgeTests(unittest.TestCase):
    def test_protocol_message_numbers_match_sddm_contract_used_by_bridge(self):
        self.assertEqual(bridge.GREETER_CONNECT, 0)
        self.assertEqual(bridge.GREETER_LOGIN, 1)
        self.assertEqual(bridge.DAEMON_HOST_NAME, 0)
        self.assertEqual(bridge.DAEMON_CAPABILITIES, 1)
        self.assertEqual(bridge.DAEMON_LOGIN_SUCCEEDED, 2)
        self.assertEqual(bridge.DAEMON_LOGIN_FAILED, 3)

    def test_preselected_atrium_session_wins(self):
        with patch.dict(
            os.environ,
            {
                "ATRIUM_SESSION_PRESELECT": "plasma.desktop",
                "ATRIUM_SESSION_LIST": "other\x1fOther\x1e",
            },
            clear=False,
        ):
            self.assertEqual(bridge._atrium_session_id(), "plasma.desktop")

    def test_plasma_session_is_preferred_from_atrium_list(self):
        with patch.dict(
            os.environ,
            {
                "ATRIUM_SESSION_PRESELECT": "",
                "ATRIUM_SESSION_LIST": (
                    "first.desktop\x1fOther Desktop\x1e"
                    "plasma.desktop\x1fPlasma (Wayland)\x1e"
                ),
            },
            clear=False,
        ):
            self.assertEqual(bridge._atrium_session_id(), "plasma.desktop")

    def test_first_session_is_fallback(self):
        with patch.dict(
            os.environ,
            {
                "ATRIUM_SESSION_PRESELECT": "",
                "ATRIUM_SESSION_LIST": "first.desktop\x1fOther Desktop\x1e",
            },
            clear=False,
        ):
            self.assertEqual(bridge._atrium_session_id(), "first.desktop")


if __name__ == "__main__":
    unittest.main()
