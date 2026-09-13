#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Execute com sudo/root." >&2; exit 1; }

WORK=/var/lib/multi-seat-arch/build
JOBS=${JOBS:-$(nproc)}
export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:${PKG_CONFIG_PATH:-}"

pacman -S --needed --noconfirm \
  git make meson ninja wget gcc cmake pkgconf patch libdrm wayland libxkbcommon \
  libinput libunwind pixman cairo libjpeg-turbo libwebp mesa pango lcms2 mtdev \
  libva colord pipewire wayland-protocols freerdp neatvnc libxml2 glib2 hwdata \
  libdisplay-info libliftoff xorg-xwayland libxcb xcb-util-renderutil xcb-util-wm

mkdir -p "$WORK"
cd "$WORK"

clone_or_update() {
  local url=$1 dir=$2 ref=${3:-}
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" fetch --all --prune
    git -C "$dir" reset --hard
  else
    git clone "$url" "$dir"
  fi
  if [[ -n "$ref" ]]; then git -C "$dir" checkout "$ref"; fi
  git -C "$dir" pull --ff-only || true
}

build_make() {
  local dir=$1
  make -C "$dir" -j"$JOBS"
  make -C "$dir" install
}

build_meson() {
  local dir=$1
  rm -rf "$dir/build"
  meson setup "$dir/build" "$dir" --buildtype=release
  ninja -C "$dir/build" -j"$JOBS"
  ninja -C "$dir/build" install
}

clone_or_update https://github.com/cktan/tomlc99.git tomlc99
[[ -f tomlc99/libtoml.pc.sample ]] && cp -f tomlc99/libtoml.pc.sample tomlc99/libtoml.pc
build_make tomlc99
ldconfig

clone_or_update https://gerrit.automotivelinux.org/gerrit/src/drm-lease-manager drm-lease-manager
if [[ -f drm-lease-manager/meson.build ]]; then build_meson drm-lease-manager; else build_make drm-lease-manager; fi
ldconfig

clone_or_update https://gitlab.freedesktop.org/wlroots/wlroots.git wlroots 0.20
wget -qO "$WORK/wlroots-multiseat.patch" https://raw.githubusercontent.com/garlett/multiseat/wlroots-0.20/multiseat.patch
if git -C wlroots apply --check "$WORK/wlroots-multiseat.patch" >/dev/null 2>&1; then
  git -C wlroots apply "$WORK/wlroots-multiseat.patch"
else
  echo "Patch já aplicado ou incompatível; verificando pelo build."
fi
build_meson wlroots
ldconfig

clone_or_update https://github.com/labwc/labwc.git labwc
mkdir -p labwc/subprojects
rm -f labwc/subprojects/wlroots
ln -s "$WORK/wlroots" labwc/subprojects/wlroots
build_meson labwc
ldconfig

for bin in /usr/local/bin/drm-lease-manager /usr/local/bin/labwc; do
  [[ -x "$bin" ]] || { echo "Falha: $bin não foi instalado." >&2; exit 2; }
done

if ldd /usr/local/bin/labwc | grep -q 'not found'; then
  echo "Falha: labwc possui bibliotecas ausentes:" >&2
  ldd /usr/local/bin/labwc | grep 'not found' >&2
  exit 3
fi

echo "Engine DRM lease instalada e validada."
