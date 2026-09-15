import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from multiseat_arch import runtime_patch, session_shell


class RuntimeCapabilityTests(unittest.TestCase):
    def test_seat_service_drops_capabilities_and_keeps_namespaces(self):
        props = runtime_patch._seat_service_properties()
        self.assertIn("PAMName=login", props)
        self.assertIn("CapabilityBoundingSet=", props)
        self.assertIn("AmbientCapabilities=", props)
        self.assertIn("RestrictNamespaces=no", props)
        self.assertIn("PrivateUsers=no", props)
        self.assertIn("NoNewPrivileges=no", props)

    def test_session_health_records_graphics_and_sandbox_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            env = {
                "XDG_RUNTIME_DIR": str(runtime),
                "XDG_SEAT": "seat-card1-HDMI-A-1",
                "WAYLAND_DISPLAY": "wayland-0",
                "DISPLAY": ":0",
            }
            with patch.dict(os.environ, env, clear=False), patch(
                "multiseat_arch.session_shell.shutil.which",
                side_effect=lambda name: f"/usr/bin/{name}" if name in {"unshare", "bwrap"} else None,
            ), patch(
                "multiseat_arch.session_shell._command_result", return_value=(0, "")
            ):
                session_shell._write_session_health()

            text = (runtime / "multi-seat-arch-health.log").read_text(encoding="utf-8")
            self.assertIn("seat=seat-card1-HDMI-A-1", text)
            self.assertIn("wayland=wayland-0", text)
            self.assertIn("display=:0", text)
            self.assertIn("unshare_rc=0", text)
            self.assertIn("bwrap_rc=0", text)


if __name__ == "__main__":
    unittest.main()
