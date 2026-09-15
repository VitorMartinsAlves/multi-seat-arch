#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script chamará sudo quando necessário." >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

sudo pacman -S --needed --noconfirm \
  python python-pyqt6 python-pip python-evdev qt6-wayland \
  libinput systemd pciutils polkit pcmanfm-qt xfce4-terminal

# Shared/disabled inputs are implemented with EVIOCGRAB + uinput clones.
# Load it now and on future boots. This is reversible and does not change the
# default systemd target.
echo uinput | sudo tee /etc/modules-load.d/multi-seat-arch.conf >/dev/null
sudo modprobe uinput

# ASTER-like activity identification needs read access to evdev nodes from the
# active local desktop session. TAG+=uaccess delegates that ACL through logind;
# it does not make /dev/input world-readable and inactive/remote users do not
# receive the access grant.
sudo install -Dm644 \
  udev/70-multi-seat-arch-input-monitor.rules \
  /etc/udev/rules.d/70-multi-seat-arch-input-monitor.rules

# systemd-logind only treats inputN devices as seat masters when they carry the
# master-of-seat tag. The upstream single-GPU multiseat implementation patches
# systemd's vendor 71-seat.rules in place; do the same semantically through a
# local rule instead, so package upgrades and recovery stay safe.
sudo install -Dm644 \
  udev/72-multi-seat-arch-seat-master.rules \
  /etc/udev/rules.d/72-multi-seat-arch-seat-master.rules

if systemctl list-unit-files multiseat.service --no-legend 2>/dev/null \
  | grep -q '^multiseat\.service'; then
  echo "Desabilitando serviço legado multiseat.service..."
  sudo systemctl disable --now multiseat.service || true
fi

# garlett/multiseat used to edit systemd's vendor 71-seat.rules in place.
# Undo only that exact mutation if it is present; our local rule above supplies
# master-of-seat without touching files owned by systemd.
LEGACY_RULE=/usr/lib/udev/rules.d/71-seat.rules
if [[ -f "$LEGACY_RULE" ]] \
  && grep -Fq 'SUBSYSTEM=="input", KERNEL=="input*", TAG+="seat", TAG+="master-of-seat"' "$LEGACY_RULE"; then
  echo "Revertendo alteração legada de 71-seat.rules..."
  sudo sed -i \
    's/SUBSYSTEM=="input", KERNEL=="input\*", TAG+="seat", TAG+="master-of-seat"/SUBSYSTEM=="input", KERNEL=="input*", TAG+="seat"/' \
    "$LEGACY_RULE"
fi

sudo udevadm control --reload
sudo udevadm trigger --subsystem-match=input --action=change || true
sudo udevadm settle || true

engine_needs_build=0
dlm_bin=$(command -v drm-lease-manager || true)
if [[ -z "$dlm_bin" || ! -x /usr/local/bin/labwc ]]; then
  engine_needs_build=1
elif ldd "$dlm_bin" 2>/dev/null | grep -q 'not found'; then
  engine_needs_build=1
elif ldd /usr/local/bin/labwc 2>/dev/null | grep -q 'not found'; then
  engine_needs_build=1
fi

if (( engine_needs_build )); then
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
