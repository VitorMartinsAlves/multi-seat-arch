import unittest
from types import SimpleNamespace
from unittest.mock import patch

from multiseat_arch.runtime_patch_v8 import _drop_fixed_user_errors, install


class DynamicLoginRuntimeTests(unittest.TestCase):
    def test_fixed_user_validation_errors_are_removed(self):
        errors = [
            "Usuário inexistente: antigo",
            "Use usuários diferentes por seat para evitar conflito de XDG_RUNTIME_DIR: antigo",
            "Conector usado por mais de um seat: card1-HDMI-A-1",
        ]
        self.assertEqual(
            _drop_fixed_user_errors(errors),
            ["Conector usado por mais de um seat: card1-HDMI-A-1"],
        )

    def test_activation_enables_dynamic_login_before_previous_backend(self):
        calls = []
        backend = SimpleNamespace(
            validate=lambda _config: ["Usuário inexistente: legado"],
            activate_now=lambda _config: calls.append("activate"),
        )

        with patch("multiseat_arch.runtime_patch_v8.dynamic_login.enabled", return_value=False), patch(
            "multiseat_arch.runtime_patch_v8.dynamic_login.enable",
            side_effect=lambda: calls.append("enable"),
        ):
            install(backend)
            self.assertEqual(backend.validate(object()), [])
            backend.activate_now(object())

        self.assertEqual(calls, ["enable", "activate"])


if __name__ == "__main__":
    unittest.main()
