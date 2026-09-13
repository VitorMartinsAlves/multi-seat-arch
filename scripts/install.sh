#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script chamará sudo quando necessário." >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

sudo pacman -S --needed --noconfirm \
  python python-pyqt6 python-pip qt6-wayland \
  libinput systemd pciutils polkit pcmanfm-qt xfce4-terminal

if systemctl list-unit-files multiseat.service --no-legend 2>/dev/null \
  | grep -q '^multiseat\.service'; then
  echo "Desabilitando serviço legado multiseat.service..."
  sudo systemctl disable --now multiseat.service || true
fi

if ! command -v drm-lease-manager >/dev/null 2>&1 \
  || [[ ! -x /usr/local/bin/labwc ]] \
  || ldd /usr/local/bin/labwc 2>/dev/null | grep -q 'not found'; then
  echo "Engine DRM lease ausente/incompleta. Compilando componentes..."
  sudo bash scripts/build-engine.sh
fi

sudo python -m pip install \
  --break-system-packages \
  --disable-pip-version-check \
  .

sudo install -Dm644 \
  desktop/multi-seat-arch.desktop \
  /usr/share/applications/multi-seat-arch.desktop

echo "Instalado. Abra 'Multi Seat Arch' no menu ou rode: multi-seat-arch-gui"
multi-seat-arch doctor || true
