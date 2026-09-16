#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script usa sudo apenas para pacman/install." >&2
  exit 1
fi

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=${WORK:-$HOME/.cache/multi-seat-arch/atrium-login}
SRC="$WORK/atrium"
BUILD="$WORK/build"
ATRIUM_REF=${ATRIUM_REF:-94db43b9e6dc6c109b03d5dd40668c938987a96e}

sudo pacman -S --needed --noconfirm \
  git base-devel meson ninja pkgconf systemd pam gtk4

export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
if ! pkg-config --exists libdlmclient; then
  echo "libdlmclient não encontrada. Rode primeiro: bash scripts/install.sh" >&2
  exit 2
fi

mkdir -p "$WORK"
if [[ -d "$SRC/.git" ]]; then
  git -C "$SRC" fetch --force origin
  git -C "$SRC" reset --hard
  git -C "$SRC" clean -fdx
else
  git clone https://github.com/kavau/atrium.git "$SRC"
fi

git -C "$SRC" fetch --depth 1 origin "$ATRIUM_REF" || true
git -C "$SRC" checkout --force "$ATRIUM_REF"

python "$REPO_DIR/scripts/patch-atrium-drm-lease.py" "$SRC"
grep -q 'MULTI_SEAT_ARCH_ATRIUM_DRM_LEASE' "$SRC/daemon/session/msa_drm_lease.c" || {
  echo "Falha: patch DRM lease do Atrium não foi aplicado." >&2
  exit 3
}

rm -rf "$BUILD"
meson setup "$BUILD" "$SRC" \
  --buildtype=release \
  --prefix=/usr \
  -Ddist=arch
ninja -C "$BUILD"
sudo ninja -C "$BUILD" install

sudo systemd-sysusers >/dev/null || true
sudo systemd-tmpfiles --create >/dev/null || true

if [[ ! -x /usr/bin/atrium || ! -x /usr/lib/atrium/atrium-gtk-greeter ]]; then
  echo "Falha: Atrium/greeter não apareceram após a instalação." >&2
  exit 4
fi

# The project runs Atrium as a transient msa-app unit. Never replace or enable
# the host display-manager.service here.
if [[ -f /etc/multi-seat-arch/dynamic-login ]]; then
  sudo multi-seat-arch login-enable
fi

echo "Atrium multiseat patchado instalado."
echo "Daemon: /usr/bin/atrium"
echo "Greeter: /usr/lib/atrium/atrium-gtk-greeter"
echo "O display-manager normal do CachyOS não foi substituído nem habilitado/desabilitado."
