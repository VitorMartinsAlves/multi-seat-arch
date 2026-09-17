#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "MULTI_SEAT_ARCH_FIXED_LEASE_FD_198"
FIXED_FD = 198


def patch_tree(root: Path) -> None:
    logind = root / "src/core/session_logind.cpp"
    if not logind.is_file():
        raise RuntimeError(f"missing KWin source file: {logind}")

    text = logind.read_text(encoding="utf-8")
    if MARKER in text:
        return

    sig = "std::expected<int, Session::Error> LogindSession::openRestricted(const QString &fileName)\n{"
    if sig not in text:
        raise RuntimeError("KWin source changed; openRestricted anchor not found")

    block = f'''std::expected<int, Session::Error> LogindSession::openRestricted(const QString &fileName)\n{{\n    // {MARKER}\n    // Atrium already acquired the DRM lease while privileged. The display\n    // manager bridge pins that capability to fd {FIXED_FD}. Prefer it whenever\n    // KWIN_DRM_LEASE identifies a managed connector, so KWin does not need to\n    // reopen /dev/dri/cardX or reacquire the lease after privilege drop.\n    const QByteArray fixedLeaseName = qgetenv("KWIN_DRM_LEASE");\n    if (!fixedLeaseName.isEmpty()\n        && fileName.startsWith(QLatin1StringView("/dev/dri/card"))\n        && fcntl({FIXED_FD}, F_GETFD) >= 0) {{\n        const int ret = fcntl({FIXED_FD}, F_DUPFD_CLOEXEC, 0);\n        if (ret < 0) {{\n            return std::unexpected(errorFromErrno());\n        }}\n        s_multiSeatLeases.emplace(ret, nullptr);\n        qCInfo(KWIN_CORE, "Using fixed display-manager DRM lease fd {FIXED_FD} for %s (dup=%d)",\n               qPrintable(fileName), ret);\n        return ret;\n    }}'''

    text = text.replace(sig, block, 1)
    logind.write_text(text, encoding="utf-8")

    final = logind.read_text(encoding="utf-8")
    if MARKER not in final or f"fcntl({FIXED_FD}, F_GETFD)" not in final:
        raise RuntimeError("fixed DRM lease fd patch validation failed")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-kwin-fixed-fd.py /path/to/kwin-source")
    patch_tree(Path(sys.argv[1]).resolve())
