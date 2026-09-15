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
from PyQt6.QtGui import QBrush, QColor, QCloseEvent, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import config as cfg
from .activity import InputActivityMonitor
from .backend import doctor, validate as validate_backend
from .device_ui import group_devices, icon_names, is_system_device, is_useful_input
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
MODE_MIXED = "__mixed__"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Multi Seat Arch")
        self.resize(1280, 820)
        self.displays = []
        self.inputs: list[InputDevice] = []
        self.rules: dict[str, DeviceRule] = {}
        self.loading = False
        self.row_for_key: dict[str, int] = {}
        self._pulse_generation: dict[str, int] = {}
        self._activity_opened = 0
        self._activity_total = 0

        self._build()
        self.activity_monitor = InputActivityMonitor(self)
        self.activity_monitor.activity.connect(self._on_device_activity)
        self.activity_monitor.availability.connect(self._activity_availability)
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
            "Gerencie monitores e periféricos em tempo real. Os ícones mostram o "
            "tipo do dispositivo e a linha pulsa quando aquele input é utilizado."
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
        self.activity_label = QLabel("")
        self.activity_label.setStyleSheet("color: palette(mid)")
        header.addWidget(self.activity_label)
        self.hardware_label = QLabel("")
        header.addWidget(self.hardware_label)

        filters = QHBoxLayout()
        device_layout.addLayout(filters)
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Buscar periférico…")
        self.search_box.setClearButtonEnabled(True)
        self.search_box.textChanged.connect(self._render_device_table)
        filters.addWidget(self.search_box, 1)

        self.group_interfaces = QCheckBox("Agrupar interfaces do mesmo dispositivo")
        self.group_interfaces.setChecked(True)
        self.group_interfaces.toggled.connect(self._render_device_table)
        filters.addWidget(self.group_interfaces)

        self.show_system = QCheckBox("Mostrar dispositivos de sistema")
        self.show_system.setChecked(False)
        self.show_system.toggled.connect(self._render_device_table)
        filters.addWidget(self.show_system)

        self.identify_activity = QCheckBox("Identificar por uso")
        self.identify_activity.setChecked(True)
        self.identify_activity.toggled.connect(self._toggle_activity_monitor)
        filters.addWidget(self.identify_activity)

        self.device_table = QTableWidget(0, 5)
        self.device_table.setHorizontalHeaderLabels(
            ["Dispositivo", "Tipo", "Conexão", "Estado", "Destino"]
        )
        self.device_table.verticalHeader().setVisible(False)
        self.device_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.device_table.setAlternatingRowColors(True)
        self.device_table.setIconSize(self.device_table.iconSize().expandedTo(self.device_table.iconSize()))
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
        create_user.clicked.connect(
            lambda _checked=False, combo=user: self.create_user(combo)
        )
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

    def _choice_for_keys(self, keys: list[str]) -> str:
        choices = {self._device_choice(self.rules.get(key)) for key in keys}
        if len(choices) == 1:
            return next(iter(choices))
        return MODE_MIXED

    def _make_destination_combo(self, keys: list[str], current: str) -> QComboBox:
        combo = QComboBox()
        if current == MODE_MIXED:
            combo.addItem("Misto (várias regras)", MODE_MIXED)
        for label, value in (
            ("Seat A", "seat-a"),
            ("Seat B", "seat-b"),
            ("Compartilhado", MODE_SHARED),
            ("Desativado", MODE_DISABLED),
            ("Sistema / seat0", MODE_UNMANAGED),
        ):
            combo.addItem(label, value)
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else combo.findData(MODE_UNMANAGED))
        combo.currentIndexChanged.connect(
            lambda _i, ks=tuple(keys), c=combo: self._rules_changed(list(ks), c)
        )
        return combo

    def _rules_changed(self, keys: list[str], combo: QComboBox) -> None:
        if self.loading:
            return
        choice = combo.currentData()
        if choice == MODE_MIXED:
            return
        present = {device.key: device for device in self.inputs}
        for key in keys:
            current = self.rules.get(key)
            name = (
                present[key].name
                if key in present
                else current.name
                if current
                else ""
            )
            if choice in {"seat-a", "seat-b"}:
                self.rules[key] = DeviceRule(key=key, mode="seat", seat=choice, name=name)
            else:
                self.rules[key] = DeviceRule(
                    key=key, mode=choice, seat="", name=name  # type: ignore[arg-type]
                )
        self.status.setText(
            "Alteração pendente. Salve ou aplique os periféricos para efetivar."
        )

    @staticmethod
    def _theme_icon(kind: str, bus: str) -> QIcon:
        for name in icon_names(kind, bus):
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
        return QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    def _render_device_table(self, _value=None) -> None:
        self.loading = True
        try:
            self.row_for_key.clear()
            search = self.search_box.text().strip().lower()
            show_system = self.show_system.isChecked()
            groups = group_devices(
                self.inputs, group_interfaces=self.group_interfaces.isChecked()
            )
            visible_groups = []
            present_keys: set[str] = set()
            for group in groups:
                present_keys.update(group.keys)
                if not show_system and all(is_system_device(item) for item in group.devices):
                    continue
                if search and search not in (
                    f"{group.name} {group.kind} {group.bus} "
                    + " ".join(item.name for item in group.devices)
                ).lower():
                    continue
                visible_groups.append(group)

            disconnected = [
                rule
                for key, rule in self.rules.items()
                if key not in present_keys
                and (not search or search in (rule.name or key).lower())
            ]
            self.device_table.setRowCount(len(visible_groups) + len(disconnected))

            row = 0
            for group in visible_groups:
                for device in group.devices:
                    rule = self.rules.get(device.key)
                    if rule is None:
                        self.rules[device.key] = DeviceRule(
                            key=device.key, mode=MODE_UNMANAGED, name=device.name
                        )
                    elif not rule.name:
                        rule.name = device.name
                    self.row_for_key[device.key] = row

                suffix = (
                    f"  ·  {len(group.devices)} interfaces"
                    if len(group.devices) > 1
                    else ""
                )
                name_item = QTableWidgetItem(f"{group.name}{suffix}")
                name_item.setIcon(self._theme_icon(group.kind, group.bus))
                members = "\n".join(
                    f"• {item.name} — {item.event}" for item in group.devices
                )
                name_item.setToolTip(
                    "Use este periférico para fazê-lo piscar na lista.\n\n" + members
                )
                values = [
                    name_item,
                    QTableWidgetItem(group.kind),
                    QTableWidgetItem(group.bus or "interno"),
                    QTableWidgetItem(group.seat),
                ]
                for col, item in enumerate(values):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.device_table.setItem(row, col, item)

                combo = self._make_destination_combo(
                    group.keys, self._choice_for_keys(group.keys)
                )
                if len(group.devices) > 1:
                    combo.setToolTip(
                        "A alteração é aplicada a todas as interfaces deste periférico."
                    )
                self.device_table.setCellWidget(row, 4, combo)
                self.device_table.setRowHeight(row, 38)
                row += 1

            for rule in disconnected:
                name = rule.name or rule.key
                item = QTableWidgetItem(name)
                item.setIcon(self._theme_icon("other", ""))
                item.setForeground(QColor("gray"))
                item.setToolTip(
                    "Periférico desconectado. A regra será mantida e reaplicada quando ele voltar."
                )
                values = [
                    item,
                    QTableWidgetItem("—"),
                    QTableWidgetItem("—"),
                    QTableWidgetItem("desconectado"),
                ]
                for col, cell in enumerate(values):
                    cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    cell.setForeground(QColor("gray"))
                    self.device_table.setItem(row, col, cell)
                combo = self._make_destination_combo(
                    [rule.key], self._device_choice(rule)
                )
                combo.setToolTip(
                    "Regra mantida: será reaplicada quando o periférico voltar."
                )
                self.device_table.setCellWidget(row, 4, combo)
                self.device_table.setRowHeight(row, 36)
                row += 1

            self.hardware_label.setText(
                f"{len(self.displays)} monitor(es) • {len(self.inputs)} input(s) • "
                f"{len(visible_groups)} periférico(s)"
            )
        finally:
            self.loading = False

    def _toggle_activity_monitor(self, enabled: bool) -> None:
        self.activity_monitor.set_devices(self.inputs if enabled else [])
        if not enabled:
            self.activity_label.setText("atividade desligada")

    def _activity_availability(self, opened: int, total: int) -> None:
        self._activity_opened = opened
        self._activity_total = total
        if not self.identify_activity.isChecked():
            self.activity_label.setText("atividade desligada")
        elif total == 0:
            self.activity_label.setText("sem inputs identificáveis")
        elif opened == total:
            self.activity_label.setText("● identificação por uso pronta")
            self.activity_label.setStyleSheet("color:#43a047")
        elif opened:
            self.activity_label.setText(f"● atividade {opened}/{total}")
            self.activity_label.setStyleSheet("color:#f9a825")
        else:
            self.activity_label.setText("atividade sem acesso aos /dev/input")
            self.activity_label.setStyleSheet("color:#e53935")

    def _on_device_activity(self, key: str) -> None:
        if not self.identify_activity.isChecked():
            return
        row = self.row_for_key.get(key)
        if row is None:
            return
        generation = self._pulse_generation.get(key, 0) + 1
        self._pulse_generation[key] = generation
        pulse = QBrush(QColor(46, 125, 50, 110))
        for col in range(4):
            item = self.device_table.item(row, col)
            if item is not None:
                item.setBackground(pulse)

        def clear() -> None:
            if self._pulse_generation.get(key) != generation:
                return
            current_row = self.row_for_key.get(key)
            if current_row is None:
                return
            for col in range(4):
                item = self.device_table.item(current_row, col)
                if item is not None:
                    item.setBackground(QBrush())

        QTimer.singleShot(480, clear)

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
        self.activity_monitor.set_devices(
            self.inputs if self.identify_activity.isChecked() else []
        )
        if bluetooth:
            self.bluetooth_note.setText(
                "Bluetooth: "
                + ", ".join(bluetooth)
                + ". O controlador fica global; HID Bluetooth pode ser movido, "
                "compartilhado, identificado por atividade ou desativado."
            )
        else:
            self.bluetooth_note.setText("Nenhum controlador Bluetooth detectado.")

    def refresh_inputs_live(self) -> None:
        try:
            new_inputs = discover_inputs()
        except Exception:
            return
        old = {(item.key, item.event, item.seat) for item in self.inputs}
        new = {(item.key, item.event, item.seat) for item in new_inputs}
        if old != new:
            self.inputs = new_inputs
            self._render_device_table()
            self.activity_monitor.set_devices(
                self.inputs if self.identify_activity.isChecked() else []
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
            if not is_useful_input(device):
                self.rules[device.key] = DeviceRule(
                    key=device.key,
                    mode=MODE_UNMANAGED,
                    name=device.name,
                )
                continue
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
            "USB/Bluetooth de usuário foi direcionado ao Seat A e teclado/touchpad "
            "internos ao Seat B. Botões de energia, tampa e Video Bus ficaram no "
            "sistema por segurança. Revise antes de iniciar.",
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

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt API
        self.activity_monitor.stop()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())
