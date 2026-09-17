from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from multiseat_arch import audio_seat
from multiseat_arch.model import Config, Seat
from multiseat_arch.runtime_patch_v12 import _valid_audio_destination


class DynamicSeatTests(unittest.TestCase):
    def test_dynamic_audio_destination_names(self) -> None:
        self.assertTrue(_valid_audio_destination("seat-a"))
        self.assertTrue(_valid_audio_destination("seat-c"))
        self.assertTrue(_valid_audio_destination("seat-27"))
        self.assertTrue(_valid_audio_destination("unmanaged"))
        self.assertFalse(_valid_audio_destination("seat0"))
        self.assertFalse(_valid_audio_destination("../seat-c"))

    def test_audio_seat_loader_accepts_third_seat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "audio.json"
            config.write_text(
                json.dumps(
                    {
                        "outputs": [
                            {"output": "alsa_output.pci-0000_00_1f.3.analog-stereo", "seat": "seat-c"},
                            {"output": "bluez_output.test", "seat": "unmanaged"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch.object(audio_seat, "AUDIO_CONFIG", config):
                self.assertEqual(
                    audio_seat._load_audio_rules(),
                    [{"output": "alsa_output.pci-0000_00_1f.3.analog-stereo", "seat": "seat-c"}],
                )

    def test_same_pci_cannot_be_split_between_seats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "audio.json"
            config_file.write_text(
                json.dumps(
                    {
                        "outputs": [
                            {"output": "alsa_output.pci-0000_00_1f.3.analog-stereo", "seat": "seat-a"},
                            {"output": "alsa_output.pci-0000_00_1f.3.hdmi-stereo", "seat": "seat-c"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            config = Config(
                seats=[
                    Seat(name="seat-a", connector="card1-HDMI-A-1", user="u"),
                    Seat(name="seat-c", connector="card1-DP-1", user="u"),
                ]
            )

            class Backend:
                @staticmethod
                def runtime_seat_name(seat):
                    return f"runtime-{seat.name}"

                @staticmethod
                def _run(*_args, **_kwargs):
                    return SimpleNamespace(returncode=0, stdout="")

            with patch.object(audio_seat, "AUDIO_CONFIG", config_file):
                with self.assertRaisesRegex(RuntimeError, "mesmo hardware ALSA/PCI"):
                    audio_seat.apply_runtime_audio_seats(config, Backend)


if __name__ == "__main__":
    unittest.main()
