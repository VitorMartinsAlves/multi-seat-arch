from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from .gui_v2 import DynamicMainWindow


LAST_ERROR = Path("/var/log/multi-seat-arch-last-error.log")


class MainWindow(DynamicMainWindow):
    def __init__(self):
        self._activation_requested_at = 0.0
        super().__init__()

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

        activation = bool(args and args[0] == "apply-start")
        if activation:
            self._activation_requested_at = time.time()
            self.status.setText("Validando e iniciando o multiseat…")
            QApplication.processEvents()

        ok = super()._pkexec(*args, timeout=timeout)
        if activation and ok:
            # The privileged command only schedules msa-activate.service. On a
            # successful transition this GUI disappears when graphical.target
            # is isolated. If it survives, inspect the asynchronous helper and
            # show its error instead of silently doing nothing.
            QTimer.singleShot(2500, self._check_activation_feedback)
            QTimer.singleShot(6000, self._check_activation_feedback)
        return ok

    def _check_activation_feedback(self) -> None:
        requested = self._activation_requested_at
        if not requested:
            return

        try:
            if LAST_ERROR.exists() and LAST_ERROR.stat().st_mtime >= requested - 1.0:
                detail = LAST_ERROR.read_text(encoding="utf-8", errors="replace").strip()
                self._activation_requested_at = 0.0
                QMessageBox.critical(
                    self,
                    "Falha ao iniciar multiseat",
                    detail or "A ativação falhou e o desktop normal foi restaurado.",
                )
                self.status.setText("Falha na ativação. O desktop normal foi restaurado.")
                return
        except OSError:
            pass

        result = subprocess.run(
            ["systemctl", "is-failed", "--quiet", "msa-activate.service"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode == 0:
            log = subprocess.run(
                [
                    "journalctl",
                    "-u",
                    "msa-activate.service",
                    "-b",
                    "--no-pager",
                    "-n",
                    "80",
                    "-o",
                    "cat",
                ],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
            ).stdout.strip()
            self._activation_requested_at = 0.0
            QMessageBox.critical(
                self,
                "Falha ao iniciar multiseat",
                log or "msa-activate.service falhou sem registrar detalhes.",
            )
            self.status.setText("Falha na ativação. Veja a mensagem acima.")
            return

        self.status.setText("Ativação em andamento… aguardando as telas de login.")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
