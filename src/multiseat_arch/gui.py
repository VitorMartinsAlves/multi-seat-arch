from __future__ import annotations

import getpass
import json
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .backend import doctor, validate as validate_backend
from .discovery import discover_displays, discover_inputs
from .model import Config, Seat


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multi Seat Arch")
        self.resize(1100, 700)
        self.displays = []
        self.inputs = []
        self._build()
        self.refresh()

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)

        title = QLabel("Multi Seat Arch")
        title.setStyleSheet("font-size: 28px; font-weight: 700")
        outer.addWidget(title)
        outer.addWidget(
            QLabel(
                "Uma GPU, estações independentes. Escolha monitor, usuário "
                "e periféricos de cada seat."
            )
        )
        self.status = QLabel("")
        outer.addWidget(self.status)

        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split, 1)
        self.a = self._seat_panel("Seat A")
        self.b = self._seat_panel("Seat B")
        split.addWidget(self.a[0])
        split.addWidget(self.b[0])

        buttons = QHBoxLayout()
        outer.addLayout(buttons)
        actions = [
            ("Detectar hardware", self.refresh),
            ("Distribuir automaticamente", self.auto_assign),
            ("Validar", self.validate_ui),
            ("Aplicar e iniciar", self.start),
            ("Restaurar PC normal", self.restore),
        ]
        for text, fn in actions:
            button = QPushButton(text)
            button.clicked.connect(fn)
            buttons.addWidget(button)

    def _seat_panel(self, title: str):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        heading = QLabel(title)
        heading.setStyleSheet("font-size: 20px; font-weight: 600")
        layout.addWidget(heading)

        monitor = QComboBox()
        layout.addWidget(QLabel("Monitor"))
        layout.addWidget(monitor)

        user = QComboBox()
        layout.addWidget(QLabel("Usuário"))
        layout.addWidget(user)

        inputs = QListWidget()
        inputs.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(QLabel("Teclado / mouse / touchpad"))
        layout.addWidget(inputs, 1)
        return widget, monitor, user, inputs

    def _users(self) -> list[str]:
        return [
            entry.pw_name
            for entry in pwd.getpwall()
            if 1000 <= entry.pw_uid < 60000
            and entry.pw_shell not in {"/usr/bin/nologin", "/bin/false"}
        ]

    def refresh(self):
        try:
            self.displays = [
                display
                for display in discover_displays()
                if display.status == "connected"
            ]
            self.inputs = discover_inputs()
        except Exception as exc:
            QMessageBox.critical(self, "Erro", str(exc))
            return

        users = self._users()
        for _, monitor, user, inputs in (self.a, self.b):
            monitor.clear()
            user.clear()
            inputs.clear()
            for display in self.displays:
                monitor.addItem(display.connector, display.connector)
            user.addItems(users)

            current = user.findText(getpass.getuser())
            if current >= 0:
                user.setCurrentIndex(current)

            for device in self.inputs:
                item = QListWidgetItem(
                    f"{device.name}  [{device.kind}]"
                    f"{' / ' + device.bus if device.bus else ''}\n"
                    f"{device.event}"
                )
                item.setData(Qt.ItemDataRole.UserRole, device.syspath)
                item.setData(Qt.ItemDataRole.UserRole + 1, device.bus)
                inputs.addItem(item)

        if len(self.displays) > 1:
            self.b[1].setCurrentIndex(1)
        if len(users) > 1:
            current = self.b[2].currentIndex()
            self.b[2].setCurrentIndex(1 if current == 0 else 0)

        self.status.setText(
            f"{len(self.displays)} monitor(es), "
            f"{len(self.inputs)} dispositivo(s) de entrada detectados"
        )

        if any("eDP" in display.connector for display in self.displays):
            self.auto_assign(silent=True)

    def _set_monitor(self, panel, connector: str) -> None:
        index = panel[1].findData(connector)
        if index >= 0:
            panel[1].setCurrentIndex(index)

    def _clear_selection(self, panel) -> None:
        panel[3].clearSelection()

    def auto_assign(self, _checked=False, *, silent: bool = False):
        if len(self.displays) < 2:
            if not silent:
                QMessageBox.warning(
                    self,
                    "Distribuição automática",
                    "Conecte pelo menos dois monitores.",
                )
            return

        internal = next(
            (display for display in self.displays if "eDP" in display.connector),
            None,
        )
        external = next(
            (
                display
                for display in self.displays
                if internal is None or display.connector != internal.connector
            ),
            None,
        )
        if not internal or not external:
            if not silent:
                QMessageBox.information(
                    self,
                    "Distribuição automática",
                    "Em desktops, selecione os periféricos manualmente para "
                    "evitar atribuições erradas.",
                )
            return

        self._set_monitor(self.a, external.connector)
        self._set_monitor(self.b, internal.connector)
        self._clear_selection(self.a)
        self._clear_selection(self.b)

        for row, device in enumerate(self.inputs):
            is_external = device.bus.lower() in {"usb", "bluetooth"}
            target = self.a if is_external else self.b
            target[3].item(row).setSelected(True)

        if not silent:
            QMessageBox.information(
                self,
                "Distribuição automática",
                "eDP recebeu os periféricos internos; o monitor externo "
                "recebeu USB/Bluetooth. Revise antes de iniciar.",
            )

    def _selected(self, panel) -> list[str]:
        return [
            item.data(Qt.ItemDataRole.UserRole)
            for item in panel[3].selectedItems()
        ]

    def build_config(self) -> Config:
        fallback = getpass.getuser()
        return Config(
            seats=[
                Seat(
                    "seat-a",
                    self.a[1].currentData() or "",
                    self.a[2].currentText() or fallback,
                    self._selected(self.a),
                ),
                Seat(
                    "seat-b",
                    self.b[1].currentData() or "",
                    self.b[2].currentText() or fallback,
                    self._selected(self.b),
                ),
            ]
        )

    def validate_ui(self) -> bool:
        config = self.build_config()
        errors = []

        if not config.seats[0].connector or not config.seats[1].connector:
            errors.append("Selecione dois monitores.")
        if config.seats[0].connector == config.seats[1].connector:
            errors.append("Cada seat precisa de um monitor diferente.")
        if not config.seats[0].inputs or not config.seats[1].inputs:
            errors.append(
                "Cada seat precisa de pelo menos um dispositivo de entrada."
            )
        if set(config.seats[0].inputs) & set(config.seats[1].inputs):
            errors.append("Um periférico não pode pertencer aos dois seats.")
        if config.seats[0].user == config.seats[1].user:
            errors.append(
                "Selecione usuários diferentes para evitar conflito "
                "entre sessões Wayland."
            )

        errors.extend(validate_backend(config))
        missing = [check.message for check in doctor(config) if not check.ok]
        if missing:
            errors.append("Pré-requisitos: " + ", ".join(missing))

        errors = list(dict.fromkeys(errors))
        QMessageBox.information(
            self,
            "Validação",
            "Configuração OK para iniciar."
            if not errors
            else "\n".join(errors),
        )
        return not errors

    def _pkexec(self, *args: str) -> bool:
        helper = shutil.which("multi-seat-arch")
        pkexec = shutil.which("pkexec")
        if not helper or not pkexec:
            QMessageBox.critical(
                self,
                "Erro",
                "multi-seat-arch ou pkexec não foi encontrado no PATH.",
            )
            return False

        try:
            proc = subprocess.run(
                [pkexec, helper, *args],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
        except subprocess.TimeoutExpired:
            QMessageBox.critical(
                self,
                "Erro",
                "A operação excedeu o tempo limite.",
            )
            return False

        if proc.returncode:
            QMessageBox.critical(
                self,
                "Erro",
                proc.stdout.strip() or f"Falha: {proc.returncode}",
            )
            return False
        return True

    def start(self):
        if not self.validate_ui():
            return

        answer = QMessageBox.question(
            self,
            "Iniciar multiseat",
            "A sessão gráfica atual será encerrada por alguns segundos. "
            "Se a inicialização falhar, o sistema tentará restaurar o "
            "desktop normal automaticamente. Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        with tempfile.NamedTemporaryFile(
            "w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as handle:
            json.dump(
                self.build_config().to_dict(),
                handle,
                indent=2,
                ensure_ascii=False,
            )
            path = handle.name

        try:
            if self._pkexec("apply", path) and self._pkexec("start"):
                self.status.setText(
                    "Inicialização agendada; a sessão atual será encerrada."
                )
        finally:
            Path(path).unlink(missing_ok=True)

    def restore(self):
        answer = QMessageBox.question(
            self,
            "Restaurar PC normal",
            "Parar todos os seats e devolver os periféricos ao seat0?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._pkexec("restore")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
