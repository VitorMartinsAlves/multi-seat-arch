import unittest

from multiseat_arch import backend
from multiseat_arch.runtime_stack import PATCH_MODULES, install


class RuntimeStackTests(unittest.TestCase):
    def test_patch_order_is_explicit_and_stable(self):
        self.assertEqual(
            PATCH_MODULES,
            (
                "runtime_patch",
                "runtime_patch_v2",
                "runtime_patch_v3",
                "runtime_patch_v4",
                "runtime_patch_v5",
                "runtime_patch_v6",
                "runtime_patch_v7",
                "runtime_patch_v8",
                "runtime_patch_v9",
                "runtime_patch_v10",
                "runtime_patch_v11",
                "runtime_patch_v12",
                "runtime_patch_v13",
                "runtime_patch_v14",
            ),
        )

    def test_stack_is_installed_once_on_package_import(self):
        self.assertTrue(getattr(backend, "_msa_runtime_stack_installed", False))
        before = backend.restore_now
        install(backend)
        self.assertIs(before, backend.restore_now)

    def test_latest_runtime_layers_are_present(self):
        self.assertTrue(getattr(backend, "_msa_runtime_patch_v13_installed", False))
        self.assertTrue(getattr(backend, "_msa_runtime_patch_v14_installed", False))


if __name__ == "__main__":
    unittest.main()
