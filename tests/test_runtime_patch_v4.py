import unittest
from unittest.mock import Mock, patch

from multiseat_arch import backend


class RuntimePatchV4Tests(unittest.TestCase):
    def test_seat_units_force_seatd_and_do_not_hide_missing_input(self):
        with patch.object(backend, "_run", return_value=Mock(stdout="", returncode=0)) as run:
            backend._systemd_run(
                "msa-seat-seat-a",
                ["labwc"],
                uid=1000,
                env={
                    "WLR_LIBINPUT_NO_DEVICES": "1",
                    "XDG_SEAT": "seat-card1-HDMI-A-1",
                },
            )

        cmd = run.call_args.args[0]
        self.assertIn("--setenv=LIBSEAT_BACKEND=seatd", cmd)
        self.assertIn("--setenv=SEATD_VTBOUND=0", cmd)
        self.assertIn("--setenv=XDG_SEAT=seat-card1-HDMI-A-1", cmd)
        self.assertFalse(any(item.startswith("--setenv=WLR_LIBINPUT_NO_DEVICES=") for item in cmd))


if __name__ == "__main__":
    unittest.main()
