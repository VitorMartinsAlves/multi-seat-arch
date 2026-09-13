from __future__ import annotations

import getpass
import json
import pwd
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget

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
        root = QWidget(); self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        title = QLabel("Multi Seat Arch")
        title.setStyleSheet("font-size: 28px; font-weight: 700")
        outer.addWidget(title)
        outer.addWidget(QLabel("Divida uma GPU em duas estações. Selecione um monitor, usuário e periféricos para cada seat."))
        self.status = QLabel(""); outer.addWidget(self.status)
        split = QSplitter(Qt.Orientation.Horizontal); outer.addWidget(split, 1)
        self.a = self._seat_panel("Seat A"); self.b = self._seat_panel("Seat B")
        split.addWidget(self.a[0]); split.addWidget(self.b[0])
        buttons = QHBoxLayout(); outer.addLayout(buttons)
        for text, fn in [("Detectar hardware", self.refresh), ("Validar", self.validate_ui), ("Aplicar e iniciar", self.start), ("Restaurar PC normal", self.restore)]:
            btn = QPushButton(text); btn.clicked.connect(fn); buttons.addWidget(btn)

    def _seat_panel(self, title: str):
        w = QWidget(); l = QVBoxLayout(w)
        h = QLabel(title); h.setStyleSheet("font-size: 20px; font-weight: 600"); l.addWidget(h)
        combo = QComboBox(); l.addWidget(QLabel("Monitor")); l.addWidget(combo)
        user = QComboBox(); l.addWidget(QLabel("Usuário")); l.addWidget(user)
        lst = QListWidget(); lst.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        l.addWidget(QLabel("Teclado / mouse / touchpad")); l.addWidget(lst, 1)
        return w, combo, user, lst

    def refresh(self):
        try:
            self.displays = [d for d in discover_displays() if d.status == "connected"]
            self.inputs = discover_inputs()
        except Exception as e:
            QMessageBox.critical(self, "Erro", str(e)); return
        users = [u.pw_name for u in pwd.getpwall() if 1000 <= u.pw_uid < 60000 and u.pw_shell not in {"/usr/bin/nologin", "/bin/false"}]
        for _, combo, user, lst in (self.a, self.b):
            combo.clear(); user.clear(); lst.clear()
            for d in self.displays: combo.addItem(d.connector, d.connector)
            user.addItems(users)
            current = user.findText(getpass.getuser())
            if current >= 0: user.setCurrentIndex(current)
            for dev in self.inputs:
                item = QListWidgetItem(f"{dev.name}  [{dev.kind}]\n{dev.event}")
                item.setData(Qt.ItemDataRole.UserRole, dev.syspath); lst.addItem(item)
        if len(self.displays) > 1: self.b[1].setCurrentIndex(1)
        if len(users) > 1: self.b[2].setCurrentIndex(1 if self.b[2].currentIndex() == 0 else 0)
        self.status.setText(f"{len(self.displays)} monitor(es), {len(self.inputs)} dispositivo(s) de entrada detectados")

    def _selected(self, panel):
        return [i.data(Qt.ItemDataRole.UserRole) for i in panel[3].selectedItems()]

    def build_config(self) -> Config:
        fallback = getpass.getuser()
        return Config(seats=[
            Seat("seat-a", self.a[1].currentData() or "", self.a[2].currentText() or fallback, self._selected(self.a)),
            Seat("seat-b", self.b[1].currentData() or "", self.b[2].currentText() or fallback, self._selected(self.b)),
        ])

    def validate_ui(self):
        c = self.build_config(); errors = []
        if not c.seats[0].connector or not c.seats[1].connector: errors.append("Selecione dois monitores.")
        if c.seats[0].connector == c.seats[1].connector: errors.append("Cada seat precisa de um monitor diferente.")
        if not c.seats[0].inputs or not c.seats[1].inputs: errors.append("Cada seat precisa de pelo menos um dispositivo de entrada.")
        if set(c.seats[0].inputs) & set(c.seats[1].inputs): errors.append("Um periférico não pode pertencer aos dois seats.")
        QMessageBox.information(self, "Validação", "Configuração visual OK." if not errors else "\n".join(errors))
        return not errors

    def _pkexec(self, *args: str):
        proc = subprocess.run(["pkexec", "multi-seat-arch", *args], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if proc.returncode: QMessageBox.critical(self, "Erro", proc.stdout or f"Falha: {proc.returncode}")
        return proc.returncode == 0

    def start(self):
        if not self.validate_ui(): return
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(self.build_config().to_dict(), f, indent=2, ensure_ascii=False); path = f.name
        if self._pkexec("apply", path): self._pkexec("start")
        Path(path).unlink(missing_ok=True)

    def restore(self):
        self._pkexec("restore")


def main():
    app = QApplication(sys.argv); w = MainWindow(); w.show(); raise SystemExit(app.exec())
