import unittest

from evdev import ecodes

from multiseat_arch.activity import _ActivityRateLimiter, _meaningful_events


class Event:
    def __init__(self, event_type: int, value: int = 0):
        self.type = event_type
        self.value = value


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

    def test_ignores_idle_syn_and_msc_noise(self):
        self.assertFalse(
            _meaningful_events(
                [Event(ecodes.EV_SYN), Event(ecodes.EV_MSC, 123)]
            )
        )
        self.assertFalse(_meaningful_events([Event(ecodes.EV_REL, 0)]))

    def test_accepts_real_user_activity(self):
        self.assertTrue(_meaningful_events([Event(ecodes.EV_REL, 3)]))
        self.assertTrue(_meaningful_events([Event(ecodes.EV_KEY, 1)]))
        self.assertTrue(_meaningful_events([Event(ecodes.EV_ABS, 100)]))


if __name__ == "__main__":
    unittest.main()
