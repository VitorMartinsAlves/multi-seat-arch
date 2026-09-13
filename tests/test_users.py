import unittest
from unittest.mock import patch

from multiseat_arch import users


class UserTests(unittest.TestCase):
    def test_rejects_unsafe_username(self):
        for value in ("Vitor", "foo bar", "a;id", "../../root", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                users.validate_username(value)

    def test_accepts_simple_username_when_missing(self):
        with patch.object(users.pwd, "getpwnam", side_effect=KeyError):
            users.validate_username("seat_b")

    def test_rejects_existing_username(self):
        with patch.object(users.pwd, "getpwnam", return_value=object()):
            with self.assertRaisesRegex(ValueError, "já existe"):
                users.validate_username("vitor")


if __name__ == "__main__":
    unittest.main()
