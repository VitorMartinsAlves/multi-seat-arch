import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multiseat_arch import audio


class AudioTests(unittest.TestCase):
    def test_discover_outputs_from_pactl_json(self):
        payload = json.dumps(
            [
                {
                    "name": "alsa_output.pci-hdmi.stereo",
                    "description": "HDMI / DisplayPort",
                    "state": "RUNNING",
                    "properties": {"device.bus": "pci"},
                }
            ]
        )
        with patch("multiseat_arch.audio.shutil.which", return_value="/usr/bin/pactl"), patch(
            "multiseat_arch.audio._run"
        ) as run:
            run.return_value.returncode = 0
            run.return_value.stdout = payload
            outputs = audio.discover_outputs()
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].name, "alsa_output.pci-hdmi.stereo")
        self.assertEqual(outputs[0].state, "RUNNING")

    def test_load_rules_accepts_only_known_seats(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.json"
            path.write_text(
                json.dumps(
                    {
                        "outputs": [
                            {"output": "speaker", "seat": "seat-a"},
                            {"output": "bad", "seat": "seat-z"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch("multiseat_arch.audio.AUDIO_CONFIG", path):
                rules = audio.load_rules()
        self.assertEqual([(r.output, r.seat) for r in rules], [("speaker", "seat-a")])


if __name__ == "__main__":
    unittest.main()
