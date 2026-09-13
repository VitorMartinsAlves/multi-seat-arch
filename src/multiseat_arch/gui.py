from __future__ import annotations

import getpass
import json
import pwd
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import config as cfg
from .backend import doctor, validate as validate_backend
from .discovery import (
    discover_bluetooth_controllers,
    discover_displays,
    discover_inputs,
)
from .model import Config, DeviceRule, InputDevice, Seat
from .status import runtime_status

MODE_UNMANAGED = "unmanaged"
MODE_SHARED = "shared"
MODE_DISABLED = "disabled"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multi Seat Arch")
        self.resize(1220, 780)
        self.displays = []
        self.inputs: list[InputDevice] = []
        self.rules: dict[str, DeviceRule] = {}
        self.loading = False
        self._build()
        self._load_saved_config()
        self.refresh_all(silent=True)

        self.hardware_timer = QTimer(self)
        self.hardware_timer.timeout.connect(self.refresh_inputs_live)
        self.hardware_timer.start(1800)

        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.refresh_runtime_status)
        self.status_timer.start(2500)
        self.refresh_runtime_status()

    def _build(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(12)

        title_row = QHBoxLayout()
        outer.addLayout(title_row)
        title = QLabel("Multi Seat Arch")
        title.setStyleSheet("font-size: 30px; font-weight: 700")
        title_row.addWidget(title)
        title_row.addStretch(1)
        self.runtime_badge = QLabel("Verificando…")
        title_row.addWidget(self.runtime_badge)

        subtitle = QLabel(
            "Gerencie monitores e periféricos em tempo real: mover, compartilhar, "
            "desativar ou devolver ao sistema sem editar arquivos."
        )
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        split = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(split)
        self.a = self._seat_panel("Seat A", "seat-a")
        self.b = self._seat_panel("Seat B", "seat-b")
        split.addWidget(self.a["widget"])
        split.addWidget(self.b["widget"])

        device_box = QFrame()
        device_box.setFrameShape(QFrame.Shape.StyledPanel)
        device_layout = QVBoxLayout(device_box)
        header = QHBoxLayout()
        device_layout.addLayout(header)
        heading = QLabel("Periféricos")
        heading.setStyleSheet("font-size: 20px; font-weight: 650")
        header.addWidget(heading)
        header.addStretch(1)
        self.hardware_label = QLabel("")
        header.addWidget(self.hardware_label)

        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels(
            ["Dispositivo", "Tipo", "Conexão", "Estado", "Destino"]
        )
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self.device_table.setAlternatingRowColors(True)
        self.device_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        for col in (1, 2, 3):
            self.device_table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.ResizeToContents
            )
        self.device_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.ResizeMode.ResizeToContents
        )
        device_layout.addWidget(self.device_table)

        self.bluetooth_note = QLabel("")
        self.bluetooth_note.setWordWrap(True)
        self.bluetooth_note.setStyleSheet("color: palette(mid)")
        device_layout.addWidget(self.bluetooth_note)
        outer.addWidget(device_box, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        outer.addWidget(self.status)

        top_actions = QHBoxLayout()
        outer.addLayout(top_actions)
        for text, fn in (
            ("Detectar hardware", self.refresh_all),
            ("Distribuir automaticamente", self.auto_assign),
            ("Salvar configuração", self.save_configuration),
        ):
            button = QPushButton(text)
            button.clicked.connect(fn)
            top_actions.addWidget(button)

        self.live_button = QPushButton("Aplicar periféricos agora")
        self.live_button.clicked.connect(self.apply_devices_live)
        top_actions.addWidget(self.live_button)

        bottom_actions = QHBoxLayout()
        outer.addLayout(bottom_actions)
        validate_button = QPushButton("Validar")
        validate_button.clicked.connect(self.validate_ui)
        bottom_actions.addWidget(validate_button)

        start_button = QPushButton("Aplicar e iniciar / reiniciar")
        start_button.clicked.connect(self.start)
        start_button.setStyleSheet("font-weight: 650; padding: 8px")
        bottom_actions.addWidget(start_button, 1)

        restore_button = QPushButton("Restaurar PC normal")
        restore_button.clicked.connect(self.restore)
        bottom_actions.addWidget(restore_button)

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
        user = QComboBox()
        layout.addWidget(QLabel("Monitor"))
        layout.addWidget(monitor)
        layout.addWidget(QLabel("Usuário"))
        user_row = QHBoxLayout()
        user_row.addWidget(user, 1)
        create_user = QPushButton("Criar usuário")
        create_user.clicked.connect(lambda _checked=False, combo=user: self.create_user(combo))
        user_row.addWidget(create_user)
        layout.addLayout(user_row)

        hint = QLabel(
            "Escolha os periféricos na tabela abaixo. Desmarque Ativo para "
            "desligar esta estação na próxima reinicialização do multiseat."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid)")
        layout.addWidget(hint)

        enabled.toggled.connect(monitor.setEnabled)
        enabled.toggled.connect(user.setEnabled)
        enabled.toggled.connect(create_user.setEnabled)
        return {
            "widget": widget,
            "name": seat_name,
            "enabled": enabled,
            "monitor": monitor,
            "user": user,
        }

    def _users(self) -> list[str]:
        return [
            entry.pw_name
            for entry in pwd.getpwall()
            if 1000 <= entry.pw_uid < 60000
            and entry.pw_shell not in {"/usr/bin/nologin", "/bin/false"}
        ]

    def create_user(self, combo: QComboBox) -> None:
        username, ok = QInputDialog.getText(
            self,
            "Criar usuário do seat",
            "Nome do novo usuário (minúsculas, sem espaços):",
        )
        username = username.strip()
        if not ok or not username:
            return
        if self._pkexec("create-user", username):
            users = self._users()
            for panel in (self.a, self.b):
                selected = panel["user"].currentText()
                panel["user"].clear()
                panel["user"].addItems(users)
                index = panel["user"].findText(selected)
                if index >= 0:
                    panel["user"].setCurrentIndex(index)
            index = combo.findText(username)
            if index >= 0:
                combo.setCurrentIndex(index)
            self.status.setText(f"Usuário '{username}' criado.")

    def _load_saved_config(self) -> None:
        try:
            saved = cfg.load()
        except (OSError, ValueError, json.JSONDecodeError):
            return
        self.rules = {rule.key: rule for rule in saved.devices}
        for seat in saved.seats:
            panel = (
                self.a
                if seat.name == "seat-a"
                else self.b
                if seat.name == "seat-b"
                else None
            )
            if panel:
                panel["enabled"].setChecked(seat.enabled)
                panel["saved_connector"] = seat.connector
                panel["saved_user"] = seat.user

    def _populate_seat_selectors(self) -> None:
        users = self._users()
        for panel in (self.a, self.b):
            saved_connector = panel.pop("saved_connector", None)
            saved_user = panel.pop("saved_user", None)
            current_connector = saved_connector or panel["monitor"].currentData()
            current_user = saved_user or panel["user"].currentText()

            panel["monitor"].clear()
            for display in self.displays:
                panel["monitor"].addItem(display.connector, display.connector)
            if current_connector:
                self._set_combo_data(panel["monitor"], current_connector)

            panel["user"].clear()
            panel["user"].addItems(users)
            wanted_user = current_user or getpass.getuser()
            index = panel["user"].findText(wanted_user)
            if index >= 0:
                panel["user"].setCurrentIndex(index)

        if len(self.displays) > 1 and (
            self.a["monitor"].currentData() == self.b["monitor"].currentData()
        ):
            self.b["monitor"].setCurrentIndex(1)
        if (
            len(users) > 1
            and self.a["user"].currentText() == self.b["user"].currentText()
        ):
            self.b["user"].setCurrentIndex(1)

    @staticmethod
    def _set_combo_data(combo: QComboBox, value: str) -> None:
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    @staticmethod
    def _device_choice(rule: DeviceRule | None) -> str:
        if not rule:
            return MODE_UNMANAGED
        return rule.seat if rule.mode == "seat" else rule.mode

    def _make_destination_combo(self, key: str, current: str) -> QComboBox:
        combo = QComboBox()
        for label, value in (
            ("Seat A", "seat-a"),
            ("Seat B", "seat-b"),
            ("Compartilhado", MODE_SHARED),
            ("Desativado", MODE_DISABLED),
            ("Sistema / seat0", MODE_UNMANAGED),
        ):
            combo.addItem(label, value)
        index = combo.findData(current)
        combo.setCurrentIndex(
            index if index >= 0 else combo.findData(MODE_UNMANAGED)
        )
        combo.currentIndexChanged.connect(
            lambda _i, k=key, c=combo: self._rule_changed(k, c)
        )
        return combo

    def _rule_changed(self, key: str, combo: QComboBox) -> None:
        if self.loading:
            return
        choice = combo.currentData()
        current = self.rules.get(key)
        name = current.name if current else ""
        if choice in {"seat-a", "seat-b"}:
            self.rules[key] = DeviceRule(
                key=key, mode="seat", seat=choice, name=name
            )
        else:
            self.rules[key] = DeviceRule(
                key=key, mode=choice, seat="", name=name  # type: ignore[arg-type]
            )
        self.status.setText(
            "Alteração pendente. Salve ou aplique os periféricos para efetivar."
        )

    def _render_device_table(self) -> None:
        self.loading = True
        try:
            present = {device.key: device for device in self.inputs}
            keys = list(present)
            keys.extend(key for key in self.rules if key not in present)
            self.device_table.setRowCount(len(keys))

            for row, key in enumerate(keys):
                device = present.get(key)
                rule = self.rules.get(key)
                if device and not rule:
                    rule = DeviceRule(
                        key=key, mode=MODE_UNMANAGED, name=device.name
                    )
                    self.rules[key] = rule
                elif device and rule and not rule.name:
                    rule.name = device.name

                name = (
                    device.name
                    if device
                    else rule.name
                    if rule and rule.name
                    else key
                )
                values = [
                    name,
                    device.kind if device else "—",
                    (device.bus or "interno") if device else "—",
                    device.seat if device else "desconectado",
                ]
                for col, value in enumerate(values):
                    item = QTableWidgetItem(str(value))
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    if not device:
                        item.setForeground(QColor("gray"))
                    self.device_table.setItem(row, col, item)

                combo = self._make_destination_combo(
                    key, self._device_choice(rule)
                )
                if not device:
                    combo.setToolTip(
                        "Regra mantida: será reaplicada quando o periférico voltar."
                    )
                self.device_table.setCellWidget(row, 4, combo)
                self.device_table.setRowHeight(row, 34)
        finally:
            self.loading = False

    def refresh_all(self, _checked=False, *, silent: bool = False) -> None:
        try:
            self.displays = [
                item for item in discover_displays() if item.status == "connected"
            ]
            self.inputs = discover_inputs()
            bluetooth = discover_bluetooth_controllers()
        except Exception as exc:
            if not silent:
                QMessageBox.critical(self, "Erro", str(exc))
            return

        self._populate_seat_selectors()
        self._render_device_table()
        self.hardware_label.setText(
            f"{len(self.displays)} monitor(es) • {len(self.inputs)} input(s)"
        )
        if bluetooth:
            self.bluetooth_note.setText(
                "Bluetooth: "
                + ", ".join(bluetooth)
                + ". O controlador fica global; HID Bluetooth (teclado, mouse, "
                "controle) pode ser movido, compartilhado ou desativado na tabela."
            )
        else:
            self.bluetooth_note.setText("Nenhum controlador Bluetooth detectado.")

    def refresh_inputs_live(self) -> None:
        try:
            new_inputs = discover_inputs()
        except Exception:
            return
        old = {(item.key, item.event) for item in self.inputs}
        new = {(item.key, item.event) for item in new_inputs}
        if old != new:
            self.inputs = new_inputs
            self._render_device_table()
            self.hardware_label.setText(
                f"{len(self.displays)} monitor(es) • {len(self.inputs)} input(s) • hotplug"
            )

    def refresh_runtime_status(self) -> None:
        try:
            status = runtime_status()
        except Exception:
            return
        running = bool(status.get("running"))
        self.live_button.setEnabled(running)
        if running:
            text = f"ATIVO • {len(status['seats'])} seat(s)"
            if status.get("hotplug"):
                text += " • hotplug"
            self.runtime_badge.setText(text)
            self.runtime_badge.setStyleSheet(
                "padding:6px 12px;border-radius:10px;background:#2f7d32;"
                "color:white;font-weight:650;"
            )
            self.live_button.setToolTip(
                "Aplica mudanças de input sem reiniciar os seats."
            )
        else:
            self.runtime_badge.setText("PC normal")
            self.runtime_badge.setStyleSheet(
                "padding:6px 12px;border-radius:10px;background:palette(midlight);"
            )
            self.live_button.setToolTip(
                "Disponível somente enquanto o multiseat estiver ativo."
            )

    def auto_assign(self, _checked=False) -> None:
        if len(self.displays) < 2:
            QMessageBox.warning(
                self,
                "Distribuição automática",
                "Conecte pelo menos dois monitores.",
            )
            return

        internal = next(
            (item for item in self.displays if "eDP" in item.connector), None
        )
        external = next(
            (
                item
                for item in self.displays
                if not internal or item.connector != internal.connector
            ),
            None,
        )
        if internal and external:
            self._set_combo_data(self.a["monitor"], external.connector)
            self._set_combo_data(self.b["monitor"], internal.connector)

        for device in self.inputs:
            target = (
                "seat-a"
                if device.bus.lower() in {"usb", "bluetooth"}
                else "seat-b"
            )
            self.rules[device.key] = DeviceRule(
                key=device.key,
                mode="seat",
                seat=target,
                name=device.name,
            )
        self._render_device_table()
        QMessageBox.information(
            self,
            "Distribuição automática",
            "USB/Bluetooth foi direcionado ao Seat A e dispositivos internos "
            "ao Seat B. Revise a tabela antes de iniciar.",
        )

    def build_config(self) -> Config:
        seats: list[Seat] = []
        for panel in (self.a, self.b):
            seats.append(
                Seat(
                    name=panel["name"],
                    connector=panel["monitor"].currentData() or "",
                    user=panel["user"].currentText() or getpass.getuser(),
                    enabled=panel["enabled"].isChecked(),
                )
            )
        return Config(version=2, seats=seats, devices=list(self.rules.values()))

    def validate_ui(self, show_message: bool = True) -> bool:
        config = self.build_config()
        errors = validate_backend(config)
        missing = [check.message for check in doctor(config) if not check.ok]
        if missing:
            errors.append("Pré-requisitos: " + ", ".join(missing))
        errors = list(dict.fromkeys(errors))
        if show_message:
            QMessageBox.information(
                self,
                "Validação",
                "Configuração OK." if not errors else "\n".join(errors),
            )
        return not errors

    def _pkexec(self, *args: str, timeout: int = 180) -> bool:
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
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            QMessageBox.critical(self, "Erro", "A operação excedeu o tempo limite.")
            return False
        if proc.returncode:
            QMessageBox.critical(
                self,
                "Erro",
                proc.stdout.strip() or f"Falha: {proc.returncode}",
            )
            return False
        return True

    def _apply_config_action(self, action: str, *, timeout: int = 180) -> bool:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8"
        ) as handle:
            json.dump(
                self.build_config().to_dict(),
                handle,
                indent=2,
                ensure_ascii=False,
            )
            path = handle.name
        try:
            return self._pkexec(action, path, timeout=timeout)
        finally:
            Path(path).unlink(missing_ok=True)

    def save_configuration(self, _checked=False) -> None:
        if not self.validate_ui(show_message=False):
            QMessageBox.warning(
                self, "Salvar", "Corrija a configuração antes de salvar."
            )
            return
        if self._apply_config_action("apply"):
            self.status.setText("Configuração salva.")

    def apply_devices_live(self, _checked=False) -> None:
        if not runtime_status().get("running"):
            QMessageBox.information(
                self,
                "Aplicação ao vivo",
                "Inicie o multiseat primeiro. No PC normal, mover os inputs para "
                "seats que ainda não existem poderia deixar você sem teclado/mouse.",
            )
            return
        if not self.validate_ui(show_message=False):
            QMessageBox.warning(
                self,
                "Aplicar periféricos",
                "Corrija a configuração antes de aplicar.",
            )
            return
        if self._apply_config_action("apply-sync", timeout=90):
            self.status.setText("Periféricos aplicados sem reiniciar os seats.")
            self.refresh_inputs_live()

    def start(self, _checked=False) -> None:
        if not self.validate_ui():
            return
        answer = QMessageBox.question(
            self,
            "Iniciar multiseat",
            "A sessão gráfica atual será encerrada durante a transição. Se algo "
            "falhar, o sistema tentará voltar ao desktop normal automaticamente. "
            "Continuar?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self._apply_config_action("apply-start"):
            self.status.setText("Configuração salva e inicialização agendada.")

    def restore(self, _checked=False) -> None:
        answer = QMessageBox.question(
            self,
            "Restaurar PC normal",
            "Parar seats, compartilhamento/desativação, DRM leases e devolver "
            "todos os inputs ao seat0?",
        )
        if answer == QMessageBox.StandardButton.Yes and self._pkexec("restore"):
            self.status.setText("Restauração agendada.")


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
