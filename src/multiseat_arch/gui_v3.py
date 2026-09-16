from __future__ import annotations

import shutil
import subprocess
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

from .gui_v2 import DynamicMainWindow


class MainWindow(DynamicMainWindow):
    def _pkexec(self, *args: str, timeout: int = 180) -> bool:
        if args and args[0] == "audio-apply":
            helper = shutil.which("multi-seat-arch-audio-admin")
            pkexec = shutil.which("pkexec")
            if not helper or not pkexec:
                QMessageBox.critical(
                    self,
                    "Erro",
                    "multi-seat-arch-audio-admin ou pkexec não foi encontrado no PATH.",
                )
                return False
            try:
                proc = subprocess.run(
                    [pkexec, helper, *args[1:]],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                QMessageBox.critical(self, "Erro", "A operação de áudio excedeu o tempo limite.")
                return False
            if proc.returncode:
                QMessageBox.critical(
                    self,
                    "Erro",
                    proc.stdout.strip() or f"Falha ao salvar áudio: {proc.returncode}",
                )
                return False
            return True
        return super()._pkexec(*args, timeout=timeout)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
