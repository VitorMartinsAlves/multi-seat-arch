import subprocess
import tempfile
import unittest
from pathlib import Path


class AtriumPatchTests(unittest.TestCase):
    def test_patcher_adds_inherited_lease_paths_idempotently(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts/patch-atrium-drm-lease.py"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "daemon/session").mkdir(parents=True)

            (root / "meson.build").write_text(
                "dep_libudev    = dependency('libudev')\n"
                "executable('atrium',\n"
                "  sources: [\n"
                "    'daemon/session/lock.c',\n"
                "    'daemon/session/session_runner.c',\n"
                "  ],\n"
                "  dependencies: [\n"
                "    dep_inih,\n"
                "    dep_libpam,\n"
                "    dep_libsystemd,\n"
                "    dep_libudev,\n"
                "  ],\n"
                ")\n"
                "executable('atrium-start-session',\n"
                "  sources: [\n"
                "    'daemon/session/lock.c',\n"
                "    'daemon/session/session_runner.c',\n"
                "  ],\n"
                "  dependencies: [\n"
                "    dep_inih,\n"
                "    dep_libpam,\n"
                "    dep_libsystemd,\n"
                "  ],\n"
                "  install: false,\n"
                ")\n",
                encoding="utf-8",
            )

            (root / "daemon/session/greeter.c").write_text(
                '#include "lib/log.h"\n\n'
                "void child_exec_greeter(void) {\n"
                "    int n_env = 0;\n"
                "    int vtnr = 0;\n"
                "    const char *session_list = \"\";\n"
                "    const char *preselect = \"\";\n"
                "    struct { const char *name; int vtnr; } seat = {\"seat-card1-HDMI-A-1\", 0};\n"
                "    typeof(seat) *s = &seat;\n"
                "    n_env += 7 + (s->vtnr > 0 ? 1 : 0) + (*session_list ? 1 : 0) + (*preselect ? 1 : 0);\n"
                "    char *env[32]; int i = 0;\n"
                '    env[i++] = "WLR_LIBINPUT_NO_DEVICES=1";\n'
                "}\n",
                encoding="utf-8",
            )

            (root / "daemon/session/compositor.h").write_text(
                "#pragma once\n"
                "typedef struct auth_result auth_result;\n"
                "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n"
                "                                     const char *session_id);\n",
                encoding="utf-8",
            )

            (root / "daemon/session/compositor.c").write_text(
                '#include "sessions.h"\n\n'
                "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n"
                "                                     const char *session_id) {\n"
                "    const char *desktop = \"KDE\";\n"
                "    int n_pam = 0;\n"
                "    int    n_env = 5 + n_pam + 4;\n"
                "    char *env[32]; int i = 0;\n"
                '    if (asprintf(&env[i++], "XDG_CURRENT_DESKTOP=%s", desktop) < 0)\n'
                "        goto oom;\n"
                "    env[i++] = NULL;\n"
                "oom:\n"
                "    _exit(1);\n"
                "}\n",
                encoding="utf-8",
            )

            (root / "daemon/session/session_runner.c").write_text(
                "void run(void) {\n"
                "    const char *username = \"martins\";\n"
                "    auth_result pam_result;\n"
                "    const char *chosen_session = \"\";\n"
                "    struct { const char *name; } seat = {\"seat-card1-HDMI-A-1\"};\n"
                "    typeof(seat) *s = &seat;\n"
                '        child_exec_compositor(username, &pam_result, chosen_session ? chosen_session : "");\n'
                "}\n",
                encoding="utf-8",
            )

            subprocess.run(["python", str(script), str(root)], check=True)
            subprocess.run(["python", str(script), str(root)], check=True)

            helper = (root / "daemon/session/msa_drm_lease.c").read_text(encoding="utf-8")
            self.assertIn("MULTI_SEAT_ARCH_ATRIUM_DRM_LEASE", helper)
            self.assertIn("dlm_get_lease", helper)
            self.assertIn("F_DUPFD", helper)
            self.assertIn("KWIN_DRM_LEASE_FD", helper)

            meson = (root / "meson.build").read_text(encoding="utf-8")
            self.assertEqual(meson.count("dep_dlmclient = dependency('libdlmclient')"), 1)
            self.assertEqual(meson.count("'daemon/session/msa_drm_lease.c'"), 2)

            greeter = (root / "daemon/session/greeter.c").read_text(encoding="utf-8")
            self.assertEqual(greeter.count("MULTI_SEAT_ARCH_ATRIUM_DRM_LEASE"), 1)
            self.assertIn("msa_drm_lease_env(s->name", greeter)

            compositor = (root / "daemon/session/compositor.c").read_text(encoding="utf-8")
            self.assertEqual(compositor.count("MULTI_SEAT_ARCH_ATRIUM_DRM_LEASE"), 1)
            self.assertIn("const char *session_id, const char *seat_name", compositor)
            self.assertIn("msa_drm_lease_env(seat_name", compositor)

            header = (root / "daemon/session/compositor.h").read_text(encoding="utf-8")
            self.assertIn("const char *session_id, const char *seat_name", header)

            runner = (root / "daemon/session/session_runner.c").read_text(encoding="utf-8")
            self.assertIn("chosen_session ? chosen_session : \"\", s->name", runner)


if __name__ == "__main__":
    unittest.main()
