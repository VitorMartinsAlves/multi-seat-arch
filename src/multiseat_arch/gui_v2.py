from __future__ import annotations

import getpass
import json
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QBrush, QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import config as cfg
from .audio import AudioOutput, AudioRule, discover_outputs, load_rules, test_output
from .gui import MainWindow
from .model import Config, Seat


class DynamicMainWindow(MainWindow):
    """GUI for display-bound seats with dynamic users and audio routing."""

    def __init__(self):
        self.audio_outputs: list[AudioOutput] = []
        self.audio_rules: dict[str, AudioRule] = {rule.output: rule for rule in load_rules()}
        self.audio_row_for_output: dict[str, int] = {}
        super().__init__()
        self.audio_timer = QTimer(self)
        self.audio_timer.timeout.connect(self.refresh_audio_live)
        self.audio_timer.start(900)
        self.refresh_audio_live(force=True)

    def _seat_panel(self, title: str, seat_name: str) -> dict:
        widget = QFrame()
        widget.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(widget)

        row = QHBoxLayout()
        layout.addLayout(row)
        heading = QLabel(title)
        heading.setStyleSheet("font-size: 20px; font-weight: 650")
        row.addWidget(heading)
        row.addStretch(1)
        enabled = QCheckBox("Ativo")
        enabled.setChecked(True)
        row.addWidget(enabled)

        monitor = QComboBox()
        layout.addWidget(QLabel("Monitor"))
        layout.addWidget(monitor)

        login = QLabel("Login dinâmico • qualquer usuário local")
        login.setStyleSheet(
            "padding:7px 9px;border-radius:7px;background:palette(alternate-base);font-weight:600"
        )
        login.setToolTip(
            "Este seat pertence à tela e aos periféricos, não a uma conta. "
            "Após logout, o greeter volta e permite escolher outro usuário."
        )
        layout.addWidget(login)

        hint = QLabel(
            "A estação é presa ao monitor, periféricos e áudio. O usuário é escolhido "
            "na tela de login e pode ser trocado livremente após logout."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid)")
        layout.addWidget(hint)

        enabled.toggled.connect(monitor.setEnabled)
        return {
            "widget": widget,
            "name": seat_name,
            "enabled": enabled,
            "monitor": monitor,
        }

    def _build(self) -> None:
        super()._build()
        outer = self.centralWidget().layout()

        audio_box = QFrame()
        audio_box.setFrameShape(QFrame.Shape.StyledPanel)
        audio_layout = QVBoxLayout(audio_box)
        header = QHBoxLayout()
        audio_layout.addLayout(header)
        heading = QLabel("Áudio")
        heading.setStyleSheet("font-size: 20px; font-weight: 650")
        header.addWidget(heading)
        header.addStretch(1)
        self.audio_status = QLabel("Detectando…")
        self.audio_status.setStyleSheet("color: palette(mid)")
        header.addWidget(self.audio_status)

        info = QLabel(
            "Caixas de som, HDMI e fones ficam verdes enquanto a saída está em uso. "
            "Use Testar para identificar fisicamente cada dispositivo antes de atribuí-lo ao seat."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: palette(mid)")
        audio_layout.addWidget(info)

        self.audio_table = QTableWidget(0, 5)
        self.audio_table.setHorizontalHeaderLabels(
            ["Saída", "Conexão", "Estado", "Destino", "Identificar"]
        )
        self.audio_table.verticalHeader().setVisible(False)
        self.audio_table.setAlternatingRowColors(True)
        self.audio_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            self.audio_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        audio_layout.addWidget(self.audio_table)

        # base layout: title, subtitle, seats, peripherals, status, actions...
        outer.insertWidget(4, audio_box)

    def _load_saved_config(self) -> None:
        try:
            saved = cfg.load()
        except (OSError, ValueError, json.JSONDecodeError):
            return
        self.rules = {rule.key: rule for rule in saved.devices}
        for seat in saved.seats:
            panel = self.a if seat.name == "seat-a" else self.b if seat.name == "seat-b" else None
            if panel:
                panel["enabled"].setChecked(seat.enabled)
                panel["saved_connector"] = seat.connector

    def _populate_seat_selectors(self) -> None:
        for panel in (self.a, self.b):
            saved_connector = panel.pop("saved_connector", None)
            current_connector = saved_connector or panel["monitor"].currentData()
            panel["monitor"].clear()
            for display in self.displays:
                panel["monitor"].addItem(display.connector, display.connector)
            if current_connector:
                self._set_combo_data(panel["monitor"], current_connector)
        if len(self.displays) > 1 and self.a["monitor"].currentData() == self.b["monitor"].currentData():
            self.b["monitor"].setCurrentIndex(1)

    def build_config(self) -> Config:
        # 'user' remains only as a legacy serialization field. Dynamic-login
        # runtime deliberately ignores it.
        legacy_user = getpass.getuser()
        seats = [
            Seat(
                name=panel["name"],
                connector=panel["monitor"].currentData() or "",
                user=legacy_user,
                enabled=panel["enabled"].isChecked(),
            )
            for panel in (self.a, self.b)
        ]
        return Config(version=2, seats=seats, devices=list(self.rules.values()))

    def _audio_destination_combo(self, output: AudioOutput) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Sistema / sem preferência", "unmanaged")
        combo.addItem("Seat A", "seat-a")
        combo.addItem("Seat B", "seat-b")
        current = self.audio_rules.get(output.name)
        wanted = current.seat if current else "unmanaged"
        index = combo.findData(wanted)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, name=output.name, desc=output.description, c=combo: self._audio_rule_changed(name, desc, c)
        )
        return combo

    def _audio_rule_changed(self, name: str, description: str, combo: QComboBox) -> None:
        seat = str(combo.currentData())
        self.audio_rules[name] = AudioRule(output=name, seat=seat, description=description)
        self.status.setText("Alteração de áudio pendente. Salve ou reinicie o multiseat para aplicar.")

    def _render_audio_table(self) -> None:
        self.audio_row_for_output.clear()
        self.audio_table.setRowCount(len(self.audio_outputs))
        for row, output in enumerate(self.audio_outputs):
            self.audio_row_for_output[output.name] = row
            name = QTableWidgetItem(output.description)
            name.setToolTip(output.name)
            bus = QTableWidgetItem(output.bus or "áudio")
            state_label = "EM USO" if output.state == "RUNNING" else output.state.lower()
            state = QTableWidgetItem(state_label)
            for col, item in enumerate((name, bus, state)):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.audio_table.setItem(row, col, item)

            self.audio_table.setCellWidget(row, 3, self._audio_destination_combo(output))
            test = QPushButton("▶ Testar")
            test.setToolTip("Toca um bip somente nesta saída para você identificar qual é.")
            test.clicked.connect(lambda _checked=False, out=output: self.test_audio_output(out))
            self.audio_table.setCellWidget(row, 4, test)
            self.audio_table.setRowHeight(row, 38)
            self._paint_audio_activity(row, output.state == "RUNNING")

        self.audio_status.setText(f"{len(self.audio_outputs)} saída(s) detectada(s)")

    def _paint_audio_activity(self, row: int, active: bool) -> None:
        brush = QBrush(QColor(46, 125, 50, 110)) if active else QBrush()
        for col in range(3):
            item = self.audio_table.item(row, col)
            if item is not None:
                item.setBackground(brush)

    def refresh_audio_live(self, *, force: bool = False) -> None:
        outputs = discover_outputs()
        old_signature = [(o.name, o.description, o.bus) for o in self.audio_outputs]
        new_signature = [(o.name, o.description, o.bus) for o in outputs]
        if force or old_signature != new_signature:
            self.audio_outputs = outputs
            self._render_audio_table()
            return

        self.audio_outputs = outputs
        by_name = {o.name: o for o in outputs}
        for name, row in self.audio_row_for_output.items():
            output = by_name.get(name)
            if output is None:
                continue
            state = self.audio_table.item(row, 2)
            if state is not None:
                state.setText("EM USO" if output.state == "RUNNING" else output.state.lower())
            self._paint_audio_activity(row, output.state == "RUNNING")

    def test_audio_output(self, output: AudioOutput) -> None:
        self.status.setText(f"Testando: {output.description}…")
        QApplication.processEvents()
        ok, detail = test_output(output.name)
        if ok:
            self.status.setText(f"Bip enviado para: {output.description}")
            self.refresh_audio_live(force=False)
        else:
            QMessageBox.warning(
                self,
                "Teste de áudio",
                detail or f"Não foi possível tocar o teste em {output.description}.",
            )

    def _save_audio_rules(self) -> bool:
        # Keep disconnected remembered outputs as well; this lets HDMI/USB audio
        # regain its seat assignment after a reconnect.
        payload = {
            "version": 1,
            "outputs": [
                {
                    "output": rule.output,
                    "seat": rule.seat,
                    "description": rule.description,
                }
                for rule in self.audio_rules.values()
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            path = handle.name
        try:
            return self._pkexec("audio-apply", path, timeout=30)
        finally:
            Path(path).unlink(missing_ok=True)

    def save_configuration(self, _checked=False) -> None:
        if not self.validate_ui(show_message=False):
            QMessageBox.warning(self, "Salvar", "Corrija a configuração antes de salvar.")
            return
        if self._apply_config_action("apply") and self._save_audio_rules():
            self.status.setText("Configuração de seats, periféricos e áudio salva.")

    def start(self, _checked=False) -> None:
        if not self.validate_ui():
            return
        answer = QMessageBox.question(
            self,
            "Iniciar multiseat",
            "A sessão gráfica atual será encerrada. Cada tela abrirá seu próprio login e "
            "usará os periféricos/áudio atribuídos ao seat. Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not self._save_audio_rules():
            return
        if self._apply_config_action("apply-start"):
            self.status.setText("Configuração salva e inicialização agendada.")


def main() -> None:
    app = QApplication(sys.argv)
    window = DynamicMainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
