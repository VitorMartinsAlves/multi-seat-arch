import unittest

from multiseat_arch.activity import _ActivityRateLimiter


class ActivityRateLimiterTests(unittest.TestCase):
    def test_limits_same_device_but_allows_other_device(self):
        limiter = _ActivityRateLimiter(interval=0.12)
        self.assertTrue(limiter.allow("mouse", 1.00))
        self.assertFalse(limiter.allow("mouse", 1.05))
        self.assertTrue(limiter.allow("keyboard", 1.05))
        self.assertTrue(limiter.allow("mouse", 1.12))

    def test_reset_allows_immediate_activity_again(self):
        limiter = _ActivityRateLimiter(interval=1.0)
        self.assertTrue(limiter.allow("mouse", 10.0))
        self.assertFalse(limiter.allow("mouse", 10.1))
        limiter.reset()
        self.assertTrue(limiter.allow("mouse", 10.1))


if __name__ == "__main__":
    unittest.main()
