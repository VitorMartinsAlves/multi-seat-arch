import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "patch_wlroots_input.py"
spec = importlib.util.spec_from_file_location("patch_wlroots_input", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


SAMPLE = '''#include <assert.h>\n#include <libudev.h>\n\nstruct wlr_device *wlr_session_open_file(struct wlr_session *session,\n\t\tconst char *path) {\n\tint fd;\n\tint device_id = libseat_open_device(session->seat_handle, path, &fd);\n\treturn NULL;\n}\n\nvoid wlr_session_close_file(struct wlr_session *session,\n\t\tstruct wlr_device *dev) {\n\tdlm_release_lease(dev->drm_lease);\n}\n'''


class PatchWlrootsInputTests(unittest.TestCase):
    def test_transform_uses_real_tabs_not_literal_backslash_t(self):
        result = module.transform_text(SAMPLE)
        self.assertIn('#include <fcntl.h>', result)
        self.assertIn('\t/* Multi Seat Arch: direct evdev open', result)
        self.assertNotIn('\\t/* Multi Seat Arch', result)
        self.assertIn('if (dev->drm_lease)', result)
        self.assertIn('Failed to directly open multiseat input', result)

    def test_transform_is_idempotent(self):
        first = module.transform_text(SAMPLE)
        second = module.transform_text(first)
        self.assertEqual(first, second)


if __name__ == '__main__':
    unittest.main()
