#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script chamará sudo quando necessário." >&2
  exit 1
fi

sudo pacman -S --needed --noconfirm python python-pyqt6 python-pip libinput systemd pciutils polkit

if ! command -v drm-lease-manager >/dev/null 2>&1 || [[ ! -x /usr/local/bin/labwc ]]; then
  echo "Engine DRM lease não encontrada. Compilando componentes necessários..."
  sudo bash scripts/build-engine.sh
fi

sudo python -m pip install --break-system-packages .
sudo install -Dm644 desktop/multi-seat-arch.desktop /usr/share/applications/multi-seat-arch.desktop

echo "Instalado. Abra 'Multi Seat Arch' no menu ou rode: multi-seat-arch-gui"
multi-seat-arch doctor || true
