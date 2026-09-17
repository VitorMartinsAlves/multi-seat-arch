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
  libinput systemd pciutils polkit acl xorg-xwayland util-linux bubblewrap desktop-file-utils libpulse sddm \
  lxqt-session lxqt-wayland-session lxqt-panel lxqt-runner lxqt-config lxqt-policykit lxqt-themes \
  pcmanfm-qt qterminal xfce4-terminal

# exp23 enabled the boot hook directly from multi-user.target while the normal
# graphical.target transaction was still pending. Disable/remove only that exact
# legacy unit during upgrade. exp24+ uses a dedicated boot target.
LEGACY_AUTOSTART=/etc/systemd/system/multi-seat-arch-autostart.service
if [[ -f "$LEGACY_AUTOSTART" ]] && grep -Fxq 'WantedBy=multi-user.target' "$LEGACY_AUTOSTART"; then
  echo "Desabilitando início automático legado da exp23 antes da migração..."
  sudo systemctl disable multi-seat-arch-autostart.service >/dev/null 2>&1 || true
  sudo rm -f "$LEGACY_AUTOSTART"
  sudo systemctl daemon-reload
fi

# Remember whether a safe exp24+ boot setup was already enabled. After the new
# Python package is installed we regenerate its unit files so watchdog/recovery
# improvements are applied without asking the user to toggle autostart off/on.
autostart_was_enabled=0
if systemctl is-enabled --quiet multi-seat-arch-autostart.service 2>/dev/null || \
   [[ "$(systemctl get-default 2>/dev/null || true)" == "multi-seat-arch.target" ]]; then
  autostart_was_enabled=1
fi

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

# KWin's own wrapper creates the XWayland display sockets/Xauthority and
# publishes DISPLAY. fd 198 is explicitly inheritable before this launcher is
# exec'd, so it remains available to the patched kwin_wayland child.
KWIN_ROOT=/opt/multi-seat-arch/kwin-plasma/usr
if [[ -x "$KWIN_ROOT/bin/kwin_wayland_wrapper" ]]; then
  sudo tee /usr/local/bin/kwin-wayland-msa >/dev/null <<'EOF'
#!/usr/bin/env bash
set -e
ROOT=/opt/multi-seat-arch/kwin-plasma/usr
export PATH="$ROOT/bin:$PATH"
export LD_LIBRARY_PATH="$ROOT/lib:${LD_LIBRARY_PATH:-}"
if [[ -d "$ROOT/lib/qt6/plugins" ]]; then
  export QT_PLUGIN_PATH="$ROOT/lib/qt6/plugins:${QT_PLUGIN_PATH:-}"
fi
exec "$ROOT/bin/kwin_wayland_wrapper" --xwayland "$@"
EOF
  sudo chmod 0755 /usr/local/bin/kwin-wayland-msa
elif [[ -x "$KWIN_ROOT/bin/kwin_wayland" ]]; then
  echo "Aviso: kwin_wayland_wrapper não está no build experimental; X11/Steam pode não funcionar." >&2
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

if (( autostart_was_enabled )); then
  helper=$(command -v multi-seat-arch || true)
  if [[ -n "$helper" ]]; then
    echo "Atualizando unidades de boot/recovery do Multi Seat Arch..."
    sudo "$helper" autostart-enable
  else
    echo "Aviso: multi-seat-arch não encontrado após instalação; unidades de autostart não foram regeneradas." >&2
  fi
fi

sudo install -Dm644 desktop/multi-seat-arch.desktop /usr/share/applications/multi-seat-arch.desktop

echo "Instalado. O Multi Seat Arch usa o greeter SDDM/KDE real nos seats multiseat."
echo "Abra 'Multi Seat Arch' no menu ou rode: multi-seat-arch-gui"
multi-seat-arch doctor || true
