#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || {
  echo "Execute com sudo/root." >&2
  exit 1
}

WORK=${WORK:-/var/lib/multi-seat-arch/build}
JOBS=${JOBS:-$(nproc)}
WLROOTS_REF=${WLROOTS_REF:-0.20.2}
LABWC_REF=${LABWC_REF:-0.20.2}

export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"

pacman -S --needed --noconfirm \
  git make meson ninja wget gcc cmake pkgconf patch \
  libdrm wayland wayland-protocols libxkbcommon libinput seatd \
  libunwind pixman cairo libjpeg-turbo libwebp libpng mesa pango \
  lcms2 mtdev libva colord pipewire freerdp neatvnc libxml2 glib2 \
  hwdata libdisplay-info libliftoff xorg-xwayland libxcb \
  xcb-util-renderutil xcb-util-wm librsvg

cat >/etc/ld.so.conf.d/multi-seat-arch.conf <<'EOF'
/usr/local/lib
/usr/local/lib64
EOF
ldconfig

mkdir -p "$WORK"
cd "$WORK"

clone_or_checkout() {
  local url=$1 dir=$2 ref=${3:-}
  if [[ -d "$dir/.git" ]]; then
    git -C "$dir" fetch --all --tags --prune
    git -C "$dir" reset --hard
    git -C "$dir" clean -fdx
  else
    git clone "$url" "$dir"
  fi

  if [[ -n "$ref" ]]; then
    git -C "$dir" checkout --force "$ref"
  else
    local branch
    branch=$(git -C "$dir" symbolic-ref --short HEAD)
    git -C "$dir" pull --ff-only origin "$branch"
  fi
}

build_make() {
  local dir=$1
  make -C "$dir" -j"$JOBS"
  make -C "$dir" install
}

build_meson() {
  local dir=$1
  shift
  rm -rf "$dir/build"
  meson setup "$dir/build" "$dir" \
    --prefix=/usr/local \
    --buildtype=release \
    "$@"
  ninja -C "$dir/build" -j"$JOBS"
  ninja -C "$dir/build" install
}

clone_or_checkout https://github.com/cktan/tomlc99.git tomlc99
if [[ -f tomlc99/libtoml.pc.sample ]]; then
  cp -f tomlc99/libtoml.pc.sample tomlc99/libtoml.pc
fi
build_make tomlc99
ldconfig

clone_or_checkout \
  https://gerrit.automotivelinux.org/gerrit/src/drm-lease-manager \
  drm-lease-manager
if [[ -f drm-lease-manager/meson.build ]]; then
  build_meson drm-lease-manager
else
  build_make drm-lease-manager
fi
ldconfig

clone_or_checkout \
  https://gitlab.freedesktop.org/wlroots/wlroots.git \
  wlroots \
  "$WLROOTS_REF"

PATCH="$WORK/wlroots-multiseat.patch"
wget -qO "$PATCH" \
  https://raw.githubusercontent.com/garlett/multiseat/wlroots-0.20/multiseat.patch

if git -C wlroots apply --check "$PATCH"; then
  git -C wlroots apply "$PATCH"
else
  echo "O patch DRM lease não é compatível com wlroots $WLROOTS_REF." >&2
  echo "Abortando para não instalar um wlroots sem suporte multiseat." >&2
  exit 2
fi

grep -q 'getenv("DRM_LEASE")' wlroots/backend/session/session.c || {
  echo "Falha: patch DRM_LEASE não foi aplicado." >&2
  exit 3
}
grep -q "dependency('libdlmclient')" wlroots/meson.build || {
  echo "Falha: wlroots não foi ligado ao libdlmclient." >&2
  exit 3
}

build_meson wlroots
ldconfig

clone_or_checkout https://github.com/labwc/labwc.git labwc "$LABWC_REF"
build_meson labwc --wrap-mode=nodownload
ldconfig

for bin in /usr/local/bin/drm-lease-manager /usr/local/bin/labwc; do
  [[ -x "$bin" ]] || {
    echo "Falha: $bin não foi instalado." >&2
    exit 4
  }

  missing=$(ldd "$bin" | grep 'not found' || true)
  if [[ -n "$missing" ]]; then
    echo "Falha: bibliotecas ausentes em $bin:" >&2
    echo "$missing" >&2
    exit 5
  fi
done

/usr/local/bin/labwc --version >/dev/null

echo "Engine DRM lease instalada e validada."
echo "wlroots: $WLROOTS_REF / labwc: $LABWC_REF"
