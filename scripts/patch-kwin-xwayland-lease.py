#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

MARKER = "MULTI_SEAT_ARCH_XWAYLAND_LEASE_FD"


def patch_tree(root: Path) -> None:
    path = root / "src/backends/drm/drm_gpu.cpp"
    if not path.is_file():
        raise RuntimeError(f"missing KWin source file: {path}")

    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        return

    old = '''FileDescriptor DrmGpu::createNonMasterFd() const
{
    char *path = drmGetDeviceNameFromFd2(m_fd);
    FileDescriptor fd{open(path, O_RDWR | O_CLOEXEC)};
    free(path);
    if (!fd.isValid()) {
        qCWarning(KWIN_DRM) << "Could not open DRM fd for leasing!" << strerror(errno);
    } else {
        if (drmIsMaster(fd.get())) {
            if (drmDropMaster(fd.get()) != 0) {
                qCWarning(KWIN_DRM) << "Could not create a non-master DRM fd for leasing!" << strerror(errno);
                return FileDescriptor{};
            }
        }
    }
    return fd;
}
'''

    new = f'''FileDescriptor DrmGpu::createNonMasterFd() const
{{
    // {MARKER}
    // In a Multi Seat Arch session m_fd is already a connector-scoped DRM
    // lease inherited from the display manager. Reopening /dev/dri/cardX here
    // defeats that isolation and also fails for secondary users that correctly
    // do not have access to the primary DRM node. XWayland only needs a DRM fd
    // representing this GPU; duplicating the existing lease keeps access
    // bounded to this seat and avoids granting the user the whole card node.
    if (!qgetenv("KWIN_DRM_LEASE_FD").isEmpty()) {{
        const int duplicatedFd = fcntl(m_fd, F_DUPFD_CLOEXEC, 0);
        if (duplicatedFd < 0) {{
            qCWarning(KWIN_DRM) << "Could not duplicate DRM lease fd for XWayland!" << strerror(errno);
            return FileDescriptor{{}};
        }}
        return FileDescriptor{{duplicatedFd}};
    }}

    char *path = drmGetDeviceNameFromFd2(m_fd);
    FileDescriptor fd{{open(path, O_RDWR | O_CLOEXEC)}};
    free(path);
    if (!fd.isValid()) {{
        qCWarning(KWIN_DRM) << "Could not open DRM fd for leasing!" << strerror(errno);
    }} else {{
        if (drmIsMaster(fd.get())) {{
            if (drmDropMaster(fd.get()) != 0) {{
                qCWarning(KWIN_DRM) << "Could not create a non-master DRM fd for leasing!" << strerror(errno);
                return FileDescriptor{{}};
            }}
        }}
    }}
    return fd;
}}
'''

    if old not in text:
        raise RuntimeError("KWin source changed; createNonMasterFd anchor not found")

    path.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch-kwin-xwayland-lease.py /path/to/kwin-source")
    patch_tree(Path(sys.argv[1]).resolve())
