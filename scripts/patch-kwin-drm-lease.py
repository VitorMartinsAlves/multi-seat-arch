#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "MULTI_SEAT_ARCH_DRM_LEASE"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"KWin source changed; anchor not found for {label}")
    return text.replace(old, new, 1)


def patch_tree(root: Path) -> None:
    top = root / "CMakeLists.txt"
    drm_cmake = root / "src/backends/drm/CMakeLists.txt"
    logind = root / "src/core/session_logind.cpp"

    for path in (top, drm_cmake, logind):
        if not path.is_file():
            raise RuntimeError(f"missing KWin source file: {path}")

    top_text = top.read_text(encoding="utf-8")
    if "pkg_check_modules(DlmClient" not in top_text:
        anchor = "pkg_check_modules(Libxcvt IMPORTED_TARGET libxcvt>=0.1.1 REQUIRED)"
        top_text = replace_once(
            top_text,
            anchor,
            anchor + "\npkg_check_modules(DlmClient IMPORTED_TARGET libdlmclient REQUIRED)",
            "libdlmclient pkg-config dependency",
        )
        top.write_text(top_text, encoding="utf-8")

    drm_text = drm_cmake.read_text(encoding="utf-8")
    if "PkgConfig::DlmClient" not in drm_text:
        drm_text = replace_once(
            drm_text,
            "target_link_libraries(kwin PRIVATE gbm::gbm PkgConfig::Libxcvt)",
            "target_link_libraries(kwin PRIVATE gbm::gbm PkgConfig::Libxcvt PkgConfig::DlmClient)",
            "kwin libdlmclient link",
        )
        drm_cmake.write_text(drm_text, encoding="utf-8")

    text = logind.read_text(encoding="utf-8")
    if MARKER in text:
        return

    include_anchor = "#include <QDBusUnixFileDescriptor>"
    # Some releases include this header through the .h instead. Place the C
    # client include after another stable system/include area if necessary.
    if include_anchor in text:
        text = replace_once(
            text,
            include_anchor,
            include_anchor + "\n#include <libdlmclient/dlmclient.h>\n#include <unordered_map>",
            "dlm include",
        )
    else:
        namespace_anchor = "namespace KWin\n{"
        text = replace_once(
            text,
            namespace_anchor,
            "#include <libdlmclient/dlmclient.h>\n#include <unordered_map>\n\n" + namespace_anchor,
            "dlm include fallback",
        )

    namespace_anchor = "namespace KWin\n{"
    globals_block = f'''namespace KWin\n{{\n\n// {MARKER}\n// Keep one lease handle for every duplicated fd handed to KWin. The handle\n// owns the manager-side lease; the duplicated fd is what KWin uses for KMS.\nstatic std::unordered_map<int, dlm_lease *> s_multiSeatLeases;\n'''
    text = replace_once(text, namespace_anchor, globals_block, "lease handle table")

    open_sig = "std::expected<int, Session::Error> LogindSession::openRestricted(const QString &fileName)\n{"
    open_body = '''std::expected<int, Session::Error> LogindSession::openRestricted(const QString &fileName)\n{\n    const QByteArray leaseName = qgetenv("KWIN_DRM_LEASE");\n    if (!leaseName.isEmpty() && fileName.startsWith(QLatin1StringView("/dev/dri/card"))) {\n        dlm_lease *lease = dlm_get_lease(leaseName.constData());\n        if (!lease) {\n            qCWarning(KWIN_CORE, "Failed to acquire external DRM lease %s for %s: %s",\n                      leaseName.constData(), qPrintable(fileName), strerror(errno));\n            return std::unexpected(Error::Other);\n        }\n        const int leaseFd = dlm_lease_fd(lease);\n        if (leaseFd < 0) {\n            dlm_release_lease(lease);\n            return std::unexpected(Error::Other);\n        }\n        const int ret = fcntl(leaseFd, F_DUPFD_CLOEXEC, 0);\n        if (ret < 0) {\n            dlm_release_lease(lease);\n            return std::unexpected(errorFromErrno());\n        }\n        s_multiSeatLeases.emplace(ret, lease);\n        qCInfo(KWIN_CORE, "Using external DRM lease %s for %s (fd=%d)",\n               leaseName.constData(), qPrintable(fileName), ret);\n        return ret;\n    }'''
    text = replace_once(text, open_sig, open_body, "openRestricted external lease")

    close_sig = "void LogindSession::closeRestricted(int fileDescriptor)\n{"
    close_body = '''void LogindSession::closeRestricted(int fileDescriptor)\n{\n    if (const auto it = s_multiSeatLeases.find(fileDescriptor); it != s_multiSeatLeases.end()) {\n        close(fileDescriptor);\n        dlm_release_lease(it->second);\n        s_multiSeatLeases.erase(it);\n        return;\n    }'''
    text = replace_once(text, close_sig, close_body, "closeRestricted external lease")

    logind.write_text(text, encoding="utf-8")

    # Fail loudly if the transformation only half-applied.
    final = logind.read_text(encoding="utf-8")
    required = [MARKER, "dlm_get_lease", "KWIN_DRM_LEASE", "s_multiSeatLeases"]
    missing = [needle for needle in required if needle not in final]
    if missing:
        raise RuntimeError("incomplete KWin DRM-lease patch: " + ", ".join(missing))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-kwin-drm-lease.py /path/to/kwin-source")
    patch_tree(Path(sys.argv[1]).resolve())
