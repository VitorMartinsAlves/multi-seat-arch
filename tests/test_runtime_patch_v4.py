import grp
import pwd
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from multiseat_arch import backend
from multiseat_arch.model import Config, Seat


class RuntimePatchV4Tests(unittest.TestCase):
    def test_seat_units_force_seatd_and_do_not_hide_missing_input(self):
        captured = {}
        previous = backend._systemd_run

        def fake(unit, command, *, uid=None, env=None, properties=None, no_block=False):
            captured.update(unit=unit, env=dict(env or {}))

        backend._systemd_run = fake
        try:
            # Reuse the public wrapper semantics without invoking hardware.
            from multiseat_arch.runtime_patch_v4 import install
            backend._msa_runtime_patch_v4_installed = False
            install(backend)
            backend._systemd_run(
                "msa-seat-seat-a",
                ["labwc"],
                uid=1000,
                env={"WLR_LIBINPUT_NO_DEVICES": "1", "XDG_SEAT": "seat-card1-HDMI-A-1"},
            )
        finally:
            backend._systemd_run = previous
            backend._msa_runtime_patch_v4_installed = True

        self.assertEqual(captured["env"]["LIBSEAT_BACKEND"], "seatd")
        self.assertEqual(captured["env"]["SEATD_VTBOUND"], "0")
        self.assertNotIn("WLR_LIBINPUT_NO_DEVICES", captured["env"])


if __name__ == "__main__":
    unittest.main()
