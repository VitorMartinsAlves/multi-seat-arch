import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from multiseat_arch import runtime_patch


class RuntimeCapabilityTests(unittest.TestCase):
    def test_seat_service_drops_capabilities_and_allows_namespaces(self):
        backend = Mock()
        backend.runtime_seat_name.return_value = "seat-card1-HDMI-A-1"
        backend._wait_for_lease.return_value = None
        backend._keyboard_layout.return_value = "br"
        backend._wait_for_wayland.return_value = "wayland-0"
        backend._resolve_binary.return_value = "/usr/local/bin/labwc"
        backend.LAST_ERROR = Path("/tmp/unused")
        backend._persist_activation_error = Mock()

        runtime_patch.install(backend)
        seat = Mock(user="martins", connector="card1-HDMI-A-1", name="seat-a")
        config = Mock(compositor="/usr/local/bin/labwc")

        account = Mock(pw_uid=1000, pw_gid=1000)
        with patch("multiseat_arch.runtime_patch.pwd.getpwnam", return_value=account), patch(
            "multiseat_arch.runtime_patch._prepare_labwc_config", return_value="/run/msa/labwc-seat-a"
        ):
            backend._start_seat(config, seat)

        props = backend._systemd_run.call_args.kwargs["properties"]
        self.assertIn("PAMName=login", props)
        self.assertIn("CapabilityBoundingSet=", props)
        self.assertIn("AmbientCapabilities=", props)
        self.assertIn("RestrictNamespaces=no", props)
        self.assertIn("PrivateUsers=no", props)


if __name__ == "__main__":
    unittest.main()
