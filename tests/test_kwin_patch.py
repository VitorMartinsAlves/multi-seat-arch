import subprocess
import tempfile
import unittest
from pathlib import Path


class KWinPatchTests(unittest.TestCase):
    def test_patcher_adds_external_lease_path_idempotently(self):
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

            subprocess.run(["python", str(script), str(root)], check=True)
            subprocess.run(["python", str(script), str(root)], check=True)

            session = (root / "src/core/session_logind.cpp").read_text(encoding="utf-8")
            self.assertIn("MULTI_SEAT_ARCH_DRM_LEASE", session)
            self.assertIn('qgetenv("KWIN_DRM_LEASE")', session)
            self.assertIn("dlm_get_lease", session)
            self.assertIn("s_multiSeatLeases", session)
            self.assertEqual(session.count("MULTI_SEAT_ARCH_DRM_LEASE"), 1)

            cmake = (root / "CMakeLists.txt").read_text(encoding="utf-8")
            self.assertEqual(cmake.count("pkg_check_modules(DlmClient"), 1)
            drm = (root / "src/backends/drm/CMakeLists.txt").read_text(encoding="utf-8")
            self.assertEqual(drm.count("PkgConfig::DlmClient"), 1)


if __name__ == "__main__":
    unittest.main()
