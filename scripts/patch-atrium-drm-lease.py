#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "MULTI_SEAT_ARCH_ATRIUM_DRM_LEASE"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"Atrium source changed; anchor not found for {label}")
    return text.replace(old, new, 1)


def patch_tree(root: Path) -> None:
    meson = root / "meson.build"
    greeter = root / "daemon/session/greeter.c"
    compositor = root / "daemon/session/compositor.c"
    compositor_h = root / "daemon/session/compositor.h"
    runner = root / "daemon/session/session_runner.c"

    for path in (meson, greeter, compositor, compositor_h, runner):
        if not path.is_file():
            raise RuntimeError(f"missing Atrium source file: {path}")

    helper_h = root / "daemon/session/msa_drm_lease.h"
    helper_c = root / "daemon/session/msa_drm_lease.c"
    helper_h.write_text(
        """#pragma once\n\n"
        "int msa_drm_lease_env(const char *seat_name, char **fd_env, char **name_env);\n",
        encoding="utf-8",
    )
    helper_c.write_text(
        f'''/* {MARKER} */
#include "msa_drm_lease.h"

#include <errno.h>
#include <fcntl.h>
#include <libdlmclient/dlmclient.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "lib/log.h"

int msa_drm_lease_env(const char *seat_name, char **fd_env, char **name_env) {{
    if (!seat_name || strncmp(seat_name, "seat-", 5) != 0) {{
        log_error("msa_drm_lease_env: unsupported seat '%s'", seat_name ? seat_name : "(null)");
        return -1;
    }}

    const char *lease_name = seat_name + 5;
    struct dlm_lease *lease = dlm_get_lease(lease_name);
    if (!lease) {{
        log_error("msa_drm_lease_env: dlm_get_lease(%s) failed: %s", lease_name, strerror(errno));
        return -1;
    }}

    const int source_fd = dlm_lease_fd(lease);
    if (source_fd < 0) {{
        log_error("msa_drm_lease_env: invalid fd for %s", lease_name);
        return -1;
    }}

    /* F_DUPFD deliberately does not set FD_CLOEXEC. The compositor is exec'd
       after Atrium drops privileges, so this duplicate is the capability that
       safely crosses the root -> login-user boundary. */
    const int inherited_fd = fcntl(source_fd, F_DUPFD, 3);
    if (inherited_fd < 0) {{
        log_syserr("msa_drm_lease_env: F_DUPFD");
        return -1;
    }}
    (void)fcntl(source_fd, F_SETFD, FD_CLOEXEC);

    if (asprintf(fd_env, "KWIN_DRM_LEASE_FD=%d", inherited_fd) < 0 ||
        asprintf(name_env, "KWIN_DRM_LEASE=%s", lease_name) < 0) {{
        close(inherited_fd);
        return -1;
    }}

    /* Do not call dlm_release_lease(): that would revoke the lease. The handle
       intentionally dies at exec while inherited_fd keeps the kernel lease
       alive until KWin exits. */
    log_info("prepared DRM lease %s as inherited fd %d", lease_name, inherited_fd);
    return 0;
}}
''',
        encoding="utf-8",
    )

    meson_text = meson.read_text(encoding="utf-8")
    if "dep_dlmclient" not in meson_text:
        meson_text = replace_once(
            meson_text,
            "dep_libudev    = dependency('libudev')",
            "dep_libudev    = dependency('libudev')\ndep_dlmclient = dependency('libdlmclient')",
            "libdlmclient dependency",
        )
        meson_text = replace_once(
            meson_text,
            "    'daemon/session/lock.c',\n    'daemon/session/session_runner.c',",
            "    'daemon/session/lock.c',\n    'daemon/session/msa_drm_lease.c',\n    'daemon/session/session_runner.c',",
            "atrium lease source",
        )
        meson_text = replace_once(
            meson_text,
            "    dep_inih,\n    dep_libpam,\n    dep_libsystemd,\n    dep_libudev,",
            "    dep_inih,\n    dep_libpam,\n    dep_libsystemd,\n    dep_libudev,\n    dep_dlmclient,",
            "atrium lease dependency",
        )
        # atrium-start-session compiles the same greeter/compositor sources.
        second_anchor = "    'daemon/session/lock.c',\n    'daemon/session/session_runner.c',"
        if second_anchor in meson_text:
            meson_text = meson_text.replace(
                second_anchor,
                "    'daemon/session/lock.c',\n    'daemon/session/msa_drm_lease.c',\n    'daemon/session/session_runner.c',",
                1,
            )
        start_dep_anchor = "    dep_inih,\n    dep_libpam,\n    dep_libsystemd,\n  ],\n  install: false,\n)"
        if start_dep_anchor in meson_text:
            meson_text = meson_text.replace(
                start_dep_anchor,
                "    dep_inih,\n    dep_libpam,\n    dep_libsystemd,\n    dep_dlmclient,\n  ],\n  install: false,\n)",
                1,
            )
        meson.write_text(meson_text, encoding="utf-8")

    greeter_text = greeter.read_text(encoding="utf-8")
    if MARKER not in greeter_text:
        greeter_text = replace_once(
            greeter_text,
            '#include "lib/log.h"',
            '#include "lib/log.h"\n#include "msa_drm_lease.h"\n\n/* ' + MARKER + ' */',
            "greeter lease include",
        )
        greeter_text = replace_once(
            greeter_text,
            "    n_env += 7 + (s->vtnr > 0 ? 1 : 0) + (*session_list ? 1 : 0) + (*preselect ? 1 : 0);",
            "    n_env += 9 + (s->vtnr > 0 ? 1 : 0) + (*session_list ? 1 : 0) + (*preselect ? 1 : 0);",
            "greeter env count",
        )
        greeter_text = replace_once(
            greeter_text,
            '    env[i++] = "WLR_LIBINPUT_NO_DEVICES=1";',
            '    env[i++] = "WLR_LIBINPUT_NO_DEVICES=1";\n'
            '    if (msa_drm_lease_env(s->name, &env[i], &env[i + 1]) < 0)\n'
            '        _exit(EXIT_FAILURE);\n'
            '    i += 2;',
            "greeter inherited lease env",
        )
        greeter.write_text(greeter_text, encoding="utf-8")

    header_text = compositor_h.read_text(encoding="utf-8")
    header_text = replace_once(
        header_text,
        "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n                                     const char *session_id);",
        "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n                                     const char *session_id, const char *seat_name);",
        "compositor header seat argument",
    )
    compositor_h.write_text(header_text, encoding="utf-8")

    compositor_text = compositor.read_text(encoding="utf-8")
    if MARKER not in compositor_text:
        compositor_text = replace_once(
            compositor_text,
            '#include "sessions.h"',
            '#include "sessions.h"\n#include "msa_drm_lease.h"\n\n/* ' + MARKER + ' */',
            "compositor lease include",
        )
        compositor_text = replace_once(
            compositor_text,
            "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n                                     const char *session_id) {",
            "_Noreturn void child_exec_compositor(const char *username, const auth_result *pam_result,\n                                     const char *session_id, const char *seat_name) {",
            "compositor seat argument",
        )
        compositor_text = replace_once(
            compositor_text,
            "    int    n_env = 5 + n_pam + 4;",
            "    int    n_env = 5 + n_pam + 6;",
            "compositor env count",
        )
        compositor_text = replace_once(
            compositor_text,
            '    if (asprintf(&env[i++], "XDG_CURRENT_DESKTOP=%s", desktop) < 0)\n        goto oom;\n    env[i++] = NULL;',
            '    if (asprintf(&env[i++], "XDG_CURRENT_DESKTOP=%s", desktop) < 0)\n'
            '        goto oom;\n'
            '    if (msa_drm_lease_env(seat_name, &env[i], &env[i + 1]) < 0)\n'
            '        _exit(EXIT_FAILURE);\n'
            '    i += 2;\n'
            '    env[i++] = NULL;',
            "compositor inherited lease env",
        )
        compositor.write_text(compositor_text, encoding="utf-8")

    runner_text = runner.read_text(encoding="utf-8")
    runner_text = replace_once(
        runner_text,
        '        child_exec_compositor(username, &pam_result, chosen_session ? chosen_session : "");',
        '        child_exec_compositor(username, &pam_result, chosen_session ? chosen_session : "", s->name);',
        "session runner compositor seat",
    )
    runner.write_text(runner_text, encoding="utf-8")

    final = "\n".join(
        [
            meson.read_text(encoding="utf-8"),
            greeter.read_text(encoding="utf-8"),
            compositor.read_text(encoding="utf-8"),
            helper_c.read_text(encoding="utf-8"),
        ]
    )
    required = [MARKER, "KWIN_DRM_LEASE_FD", "msa_drm_lease_env", "dep_dlmclient"]
    missing = [needle for needle in required if needle not in final]
    if missing:
        raise RuntimeError("incomplete Atrium DRM-lease patch: " + ", ".join(missing))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-atrium-drm-lease.py /path/to/atrium-source")
    patch_tree(Path(sys.argv[1]).resolve())
