import unittest

from multiseat_arch import backend


class RuntimePatchV5Tests(unittest.TestCase):
    def test_hotplug_watcher_is_stable_noop(self):
        self.assertIsNone(backend._start_hotplug_watcher())


if __name__ == "__main__":
    unittest.main()
