#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script chamará sudo quando necessário." >&2
  exit 1
fi

sudo pacman -S --needed --noconfirm python python-pyqt6 libinput systemd pciutils polkit
python -m pip install --user --break-system-packages .

BIN="$HOME/.local/bin"
sudo install -Dm644 desktop/multi-seat-arch.desktop /usr/share/applications/multi-seat-arch.desktop
sudo sed -i "s|Exec=multi-seat-arch-gui|Exec=$BIN/multi-seat-arch-gui|" /usr/share/applications/multi-seat-arch.desktop

echo "Instalado. Rode: $BIN/multi-seat-arch-gui"
echo "Antes de iniciar seats, rode: $BIN/multi-seat-arch doctor"
