from __future__ import annotations

import getpass
import json

from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
)

from . import config as cfg
from .gui import MODE_DISABLED, MODE_MIXED, MODE_SHARED, MODE_UNMANAGED
from .gui_v3 import MainWindow as PreviousMainWindow
from .model import Config, DeviceRule, Seat


class MainWindow(PreviousMainWindow):
    """Dynamic-seat GUI: one seat panel per configured/connected display."""

    def _build(self) -> None:
        super()._build()
        self.seat_panels: list[dict] = [self.a, self.b]
        self.seat_splitter = self.a["widget"].parentWidget()

        controls = QHBoxLayout()
        hint = QLabel("Seats podem ser adicionados para cada monitor conectado.")
        hint.setStyleSheet("color: palette(mid)")
        controls.addWidget(hint)
        controls.addStretch(1)
        add_button = QPushButton("+ Adicionar seat")
        add_button.clicked.connect(self.add_seat)
        controls.addWidget(add_button)
        self.remove_seat_button = QPushButton("Remover último seat")
        self.remove_seat_button.clicked.connect(self.remove_last_seat)
        controls.addWidget(self.remove_seat_button)
        self.centralWidget().layout().insertLayout(3, controls)
        self._update_remove_button()

    @staticmethod
    def _seat_suffix(index: int) -> str:
        # 0 -> a, 25 -> z, then stable numeric names.
        return chr(ord("a") + index) if index < 26 else str(index + 1)

    @classmethod
    def _seat_name_for_index(cls, index: int) -> str:
        return f"seat-{cls._seat_suffix(index)}"

    @classmethod
    def _seat_title_for_index(cls, index: int) -> str:
        suffix = cls._seat_suffix(index)
        return f"Seat {suffix.upper()}" if suffix.isalpha() else f"Seat {suffix}"

    def _panel_by_name(self, name: str) -> dict | None:
        return next((panel for panel in self.seat_panels if panel["name"] == name), None)

    def _append_seat_panel(self, *, name: str | None = None, enabled: bool = False) -> dict:
        index = len(self.seat_panels)
        name = name or self._seat_name_for_index(index)
        if self._panel_by_name(name):
            return self._panel_by_name(name)  # type: ignore[return-value]
        panel = self._seat_panel(self._seat_title_for_index(index), name)
        panel["enabled"].setChecked(enabled)
        self.seat_panels.append(panel)
        self.seat_splitter.addWidget(panel["widget"])
        self._update_remove_button()
        return panel

    def _update_remove_button(self) -> None:
        if hasattr(self, "remove_seat_button"):
            self.remove_seat_button.setEnabled(len(getattr(self, "seat_panels", [])) > 2)

    def add_seat(self, _checked=False) -> None:
        panel = self._append_seat_panel(enabled=True)
        self._populate_one_panel(panel)
        self._render_device_table()
        self._render_audio_table()
        self.status.setText(f"{panel['name']} adicionado. Escolha monitor e periféricos.")

    def remove_last_seat(self, _checked=False) -> None:
        if len(self.seat_panels) <= 2:
            return
        panel = self.seat_panels[-1]
        name = panel["name"]
        answer = QMessageBox.question(
            self,
            "Remover seat",
            f"Remover {name}? Periféricos e áudio atribuídos a ele voltarão para Sistema / seat0.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for key, rule in list(self.rules.items()):
            if rule.mode == "seat" and rule.seat == name:
                self.rules[key] = DeviceRule(key=key, mode=MODE_UNMANAGED, name=rule.name)
        for rule in self.audio_rules.values():
            if rule.seat == name:
                rule.seat = "unmanaged"
        self.seat_panels.pop()
        panel["widget"].setParent(None)
        panel["widget"].deleteLater()
        self._update_remove_button()
        self._render_device_table()
        self._render_audio_table()
        self.status.setText(f"{name} removido.")

    def _ensure_panel_count(self, count: int) -> None:
        while len(self.seat_panels) < count:
            self._append_seat_panel(enabled=False)

    def _load_saved_config(self) -> None:
        try:
            saved = cfg.load()
        except (OSError, ValueError, json.JSONDecodeError):
            return
        self.rules = {rule.key: rule for rule in saved.devices}
        for seat in saved.seats:
            panel = self._panel_by_name(seat.name)
            if panel is None:
                panel = self._append_seat_panel(name=seat.name, enabled=seat.enabled)
            panel["enabled"].setChecked(seat.enabled)
            panel["saved_connector"] = seat.connector

    def _populate_one_panel(self, panel: dict) -> None:
        saved_connector = panel.pop("saved_connector", None)
        current_connector = saved_connector or panel["monitor"].currentData()
        panel["monitor"].clear()
        for display in self.displays:
            panel["monitor"].addItem(display.connector, display.connector)
        if current_connector:
            self._set_combo_data(panel["monitor"], current_connector)

    def _populate_seat_selectors(self) -> None:
        self._ensure_panel_count(max(2, len(self.displays)))
        wanted: dict[str, str] = {}
        for panel in self.seat_panels:
            saved = panel.get("saved_connector") or panel["monitor"].currentData()
            if saved:
                wanted[panel["name"]] = str(saved)
            self._populate_one_panel(panel)

        used: set[str] = set()
        for panel in self.seat_panels:
            connector = wanted.get(panel["name"], "")
            if connector and connector not in used:
                self._set_combo_data(panel["monitor"], connector)
                if panel["monitor"].currentData() == connector:
                    used.add(connector)

        available = [d.connector for d in self.displays if d.connector not in used]
        for panel in self.seat_panels:
            current = panel["monitor"].currentData()
            if current in used:
                continue
            if available:
                connector = available.pop(0)
                self._set_combo_data(panel["monitor"], connector)
                used.add(connector)

    def build_config(self) -> Config:
        legacy_user = getpass.getuser()
        seats = [
            Seat(
                name=panel["name"],
                connector=panel["monitor"].currentData() or "",
                user=legacy_user,
                enabled=panel["enabled"].isChecked(),
            )
            for panel in self.seat_panels
        ]
        return Config(version=2, seats=seats, devices=list(self.rules.values()))

    def _make_destination_combo(self, keys: list[str], current: str) -> QComboBox:
        combo = QComboBox()
        if current == MODE_MIXED:
            combo.addItem("Misto (várias regras)", MODE_MIXED)
        for panel in self.seat_panels:
            label = self._seat_title_for_index(self.seat_panels.index(panel))
            if not panel["enabled"].isChecked():
                label += " (desativado)"
            combo.addItem(label, panel["name"])
        for label, value in (
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
        choice = str(combo.currentData())
        if choice == MODE_MIXED:
            return
        seat_names = {panel["name"] for panel in self.seat_panels}
        present = {device.key: device for device in self.inputs}
        for key in keys:
            current = self.rules.get(key)
            name = present[key].name if key in present else current.name if current else ""
            if choice in seat_names:
                self.rules[key] = DeviceRule(key=key, mode="seat", seat=choice, name=name)
            else:
                self.rules[key] = DeviceRule(key=key, mode=choice, seat="", name=name)  # type: ignore[arg-type]
        self.status.setText("Alteração pendente. Salve ou aplique os periféricos para efetivar.")

    def _audio_destination_combo(self, output) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Sistema / sem preferência", "unmanaged")
        for index, panel in enumerate(self.seat_panels):
            label = self._seat_title_for_index(index)
            if not panel["enabled"].isChecked():
                label += " (desativado)"
            combo.addItem(label, panel["name"])
        current = self.audio_rules.get(output.name)
        wanted = current.seat if current else "unmanaged"
        index = combo.findData(wanted)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.currentIndexChanged.connect(
            lambda _i, name=output.name, desc=output.description, c=combo: self._audio_rule_changed(name, desc, c)
        )
        return combo

    def auto_assign(self, _checked=False) -> None:
        if not self.displays:
            QMessageBox.warning(self, "Distribuição automática", "Nenhum monitor conectado.")
            return
        self._ensure_panel_count(max(2, len(self.displays)))
        ordered = [d for d in self.displays if "eDP" not in d.connector]
        ordered += [d for d in self.displays if "eDP" in d.connector]
        for index, panel in enumerate(self.seat_panels):
            if index < len(ordered):
                panel["enabled"].setChecked(True)
                self._set_combo_data(panel["monitor"], ordered[index].connector)
            elif index >= 2:
                panel["enabled"].setChecked(False)

        internal_panel = next(
            (p for p in self.seat_panels if "eDP" in str(p["monitor"].currentData() or "")),
            None,
        )
        external_panel = next((p for p in self.seat_panels if p is not internal_panel and p["enabled"].isChecked()), None)
        for device in self.inputs:
            from .device_ui import is_system_device, is_useful_input
            if not is_useful_input(device) or is_system_device(device):
                self.rules[device.key] = DeviceRule(key=device.key, mode=MODE_UNMANAGED, name=device.name)
                continue
            target = external_panel if device.bus.lower() in {"usb", "bluetooth"} else internal_panel
            if target is None:
                self.rules[device.key] = DeviceRule(key=device.key, mode=MODE_UNMANAGED, name=device.name)
            else:
                self.rules[device.key] = DeviceRule(key=device.key, mode="seat", seat=target["name"], name=device.name)
        self._render_device_table()
        self._render_audio_table()
        QMessageBox.information(
            self,
            "Distribuição automática",
            "Monitores foram distribuídos entre os seats detectados. Inputs internos foram para o seat da tela interna; USB/Bluetooth para o primeiro seat externo. Revise seats adicionais antes de iniciar.",
        )


def main() -> None:
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
