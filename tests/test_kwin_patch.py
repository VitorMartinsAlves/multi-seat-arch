import subprocess
import tempfile
import unittest
from pathlib import Path


class KWinPatchTests(unittest.TestCase):
    def test_patcher_adds_external_lease_paths_idempotently(self):
        repo = Path(__file__).resolve().parents[1]
        script = repo / "scripts/patch-kwin-drm-lease.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src/backends/drm").mkdir(parents=True)
            (root / "src/core").mkdir(parents=True)
            (root / "CMakeLists.txt").write_text(
                "pkg_check_modules(Libxcvt IMPORTED_TARGET libxcvt>=0.1.1 REQUIRED)\n",
                encoding="utf-8",
            )
            (root / "src/backends/drm/CMakeLists.txt").write_text(
                "target_link_libraries(kwin PRIVATE gbm::gbm PkgConfig::Libxcvt)\n",
                encoding="utf-8",
            )
            (root / "src/core/session_logind.cpp").write_text(
                "#include <QDBusUnixFileDescriptor>\n\n"
                "namespace KWin\n{\n\n"
                "std::expected<int, Session::Error> LogindSession::openRestricted(const QString &fileName)\n"
                "{\n    return 1;\n}\n\n"
                "void LogindSession::closeRestricted(int fileDescriptor)\n"
                "{\n    close(fileDescriptor);\n}\n\n"
                "} // namespace KWin\n",
                encoding="utf-8",
            )
            (root / "src/core/drmdevice.cpp").write_text(
                "#include <fcntl.h>\n\n"
                "namespace KWin\n{\n\n"
                "std::unique_ptr<DrmDevice> DrmDevice::openWithAuthentication(const QString &path, int authenticatedFd)\n"
                "{\n"
                "    FileDescriptor fd(::open(path.toLocal8Bit(), O_RDWR | O_CLOEXEC));\n"
                "    if (!fd.isValid()) {\n"
                "        qCWarning(KWIN_CORE, \"Failed to open drm node %s: %s\", qPrintable(path), strerror(errno));\n"
                "        return nullptr;\n"
                "    }\n"
                "    struct stat buf;\n"
                "    if (fstat(fd.get(), &buf) == -1) { return nullptr; }\n"
                "    if (authenticatedFd != -1) {\n"
                "        drm_magic_t magic;\n"
                "    }\n"
                "    gbm_device *device = gbm_create_device(fd.get());\n"
                "    return std::unique_ptr<DrmDevice>(new DrmDevice(path, buf.st_rdev, std::move(fd), device));\n"
                "}\n\n"
                "} // namespace KWin\n",
                encoding="utf-8",
            )

            subprocess.run(["python", str(script), str(root)], check=True)
            subprocess.run(["python", str(script), str(root)], check=True)

            session = (root / "src/core/session_logind.cpp").read_text(encoding="utf-8")
            self.assertIn("MULTI_SEAT_ARCH_DRM_LEASE", session)
            self.assertIn('qgetenv("KWIN_DRM_LEASE")', session)
            self.assertIn('qgetenv("KWIN_DRM_LEASE_FD")', session)
            self.assertIn("Using display-manager DRM lease fd", session)
            self.assertIn("dlm_get_lease", session)
            self.assertIn("s_multiSeatLeases", session)
            self.assertIn("it->second", session)
            self.assertEqual(session.count("MULTI_SEAT_ARCH_DRM_LEASE"), 1)

            device = (root / "src/core/drmdevice.cpp").read_text(encoding="utf-8")
            self.assertIn("MULTI_SEAT_ARCH_DRMDEVICE_LEASE_FD", device)
            self.assertIn("useExternalLease", device)
            self.assertIn('qgetenv("KWIN_DRM_LEASE_FD")', device)
            self.assertIn("F_DUPFD_CLOEXEC", device)
            self.assertIn("Using external DRM lease fd directly", device)
            self.assertIn("authenticatedFd != -1 && !useExternalLease", device)
            self.assertEqual(device.count("MULTI_SEAT_ARCH_DRMDEVICE_LEASE_FD"), 1)

            cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertEqual(cmake.count("pkg_check_modules(DlmClient"), 1)
            drm = (root / "src/backends/drm/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertEqual(drm.count("PkgConfig::DlmClient"), 1)


if __name__ == "__main__":
    unittest.main()
