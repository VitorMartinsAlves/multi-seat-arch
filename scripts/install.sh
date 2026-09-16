#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script chamará sudo quando necessário." >&2
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

ENGINE_REV=direct-input-v3
ENGINE_STAMP=/usr/local/share/multi-seat-arch/engine-version

sudo pacman -S --needed --noconfirm \
  python python-pyqt6 python-pip python-evdev qt6-wayland \
  libinput systemd pciutils polkit acl xorg-xwayland util-linux bubblewrap desktop-file-utils libpulse \
  lxqt-session lxqt-wayland-session lxqt-panel lxqt-runner lxqt-config lxqt-policykit lxqt-themes \
  pcmanfm-qt qterminal xfce4-terminal

sudo bash scripts/configure-userns.sh "$USER"

echo uinput | sudo tee /etc/modules-load.d/multi-seat-arch.conf >/dev/null
sudo modprobe uinput

sudo install -Dm644 udev/70-multi-seat-arch-input-monitor.rules /etc/udev/rules.d/70-multi-seat-arch-input-monitor.rules
sudo install -Dm644 udev/72-multi-seat-arch-seat-master.rules /etc/udev/rules.d/72-multi-seat-arch-seat-master.rules

if systemctl list-unit-files multiseat.service --no-legend 2>/dev/null | grep -q '^multiseat\.service'; then
  echo "Desabilitando serviço legado multiseat.service..."
  sudo systemctl disable --now multiseat.service || true
fi

LEGACY_RULE=/usr/lib/udev/rules.d/71-seat.rules
if [[ -f "$LEGACY_RULE" ]] && grep -Fq 'SUBSYSTEM=="input", KERNEL=="input*", TAG+="seat", TAG+="master-of-seat"' "$LEGACY_RULE"; then
  echo "Revertendo alteração legada de 71-seat.rules..."
  sudo sed -i 's/SUBSYSTEM=="input", KERNEL=="input\*", TAG+="seat", TAG+="master-of-seat"/SUBSYSTEM=="input", KERNEL=="input*", TAG+="seat"/' "$LEGACY_RULE"
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
elif [[ ! -f "$ENGINE_STAMP" ]] || [[ "$(cat "$ENGINE_STAMP" 2>/dev/null || true)" != "$ENGINE_REV" ]]; then
  echo "Engine multiseat antiga detectada; recompilando suporte de input direto..."
  engine_needs_build=1
fi

if (( engine_needs_build )); then
  echo "Compilando engine DRM lease + input multiseat..."
  sudo bash scripts/build-engine.sh
fi

# Existing KWin builds do not need a full rebuild for the launcher fix. The
# patched binary already lives under /opt; replace only the launcher so the DRM
# lease fd inherited from Atrium reaches kwin_wayland without an intermediate
# kwin_wayland_wrapper process.
if [[ -x /opt/multi-seat-arch/kwin-plasma/usr/bin/kwin_wayland ]]; then
  sudo tee /usr/local/bin/kwin-wayland-msa >/dev/null <<'EOF'
#!/usr/bin/env bash
set -e
ROOT=/opt/multi-seat-arch/kwin-plasma/usr
export PATH="$ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT/lib:${LD_LIBRARY_PATH:-}"
if [[ -d "$ROOT/lib/qt6/plugins" ]]; then
  export QT_PLUGIN_PATH="$ROOT/lib/qt6/plugins:${QT_PLUGIN_PATH:-}"
fi
exec "$ROOT/bin/kwin_wayland" --xwayland "$@"
EOF
  sudo chmod 0755 /usr/local/bin/kwin-wayland-msa
fi

sudo python -m pip install --break-system-packages --disable-pip-version-check .

sudo install -Dm644 desktop/multi-seat-arch.desktop /usr/share/applications/multi-seat-arch.desktop

echo "Instalado. O Multi Seat Arch não força mais tema visual; LXQt volta a controlar aparência, ícones e cores."
echo "Abra 'Multi Seat Arch' no menu ou rode: multi-seat-arch-gui"
multi-seat-arch doctor || true
