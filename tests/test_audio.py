import json
import subprocess
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

    def test_json_parser_tolerates_warning_prefix(self):
        payload = 'warning from backend\n[{"name":"sink.a","description":"Speaker","state":"IDLE"}]'
        outputs = audio._parse_pactl_sinks(payload)
        self.assertEqual([(o.name, o.description) for o in outputs], [("sink.a", "Speaker")])

    def test_discovery_falls_back_to_plain_pactl_text(self):
        plain = """Sink #52
        State: RUNNING
        Name: alsa_output.pci-0000_03_00.1.hdmi-stereo
        Description: HDMI / DisplayPort
        Properties:
                device.bus = \"pci\"
                media.class = \"Audio/Sink\"
"""
        responses = [
            subprocess.CompletedProcess([], 0, "not-json"),
            subprocess.CompletedProcess([], 0, plain),
        ]
        with patch("multiseat_arch.audio.shutil.which", return_value="/usr/bin/pactl"), patch(
            "multiseat_arch.audio._run", side_effect=responses
        ):
            outputs, detail = audio.discover_outputs_diagnostic(activate_stack=False)
        self.assertEqual(detail, "")
        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0].description, "HDMI / DisplayPort")
        self.assertEqual(outputs[0].state, "RUNNING")
        self.assertEqual(outputs[0].bus, "pci")

    def test_load_rules_accepts_dynamic_seats_and_rejects_invalid_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "audio.json"
            path.write_text(
                json.dumps(
                    {
                        "outputs": [
                            {"output": "speaker", "seat": "seat-a"},
                            {"output": "third", "seat": "seat-z"},
                            {"output": "bad", "seat": "../seat-z"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch("multiseat_arch.audio.AUDIO_CONFIG", path):
                rules = audio.load_rules()
        self.assertEqual(
            [(r.output, r.seat) for r in rules],
            [("speaker", "seat-a"), ("third", "seat-z")],
        )


if __name__ == "__main__":
    unittest.main()
