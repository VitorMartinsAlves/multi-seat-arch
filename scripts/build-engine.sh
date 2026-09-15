#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || {
  echo "Execute com sudo/root." >&2
  exit 1
}

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=${WORK:-/var/lib/multi-seat-arch/build}
JOBS=${JOBS:-$(nproc)}
WLROOTS_REF=${WLROOTS_REF:-0.20.2}
LABWC_REF=${LABWC_REF:-0.20.2}
ENGINE_REV=direct-input-v3

export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"

pacman -S --needed --noconfirm \
  git make meson ninja wget gcc cmake pkgconf patch acl \
  libdrm wayland wayland-protocols libxkbcommon libinput seatd \
  libunwind pixman cairo libjpeg-turbo libwebp libpng mesa pango \
  lcms2 mtdev libva colord pipewire freerdp neatvnc aml libxml2 glib2 \
  hwdata libdisplay-info libliftoff xorg-xwayland libxcb \
  xcb-util-renderutil xcb-util-wm librsvg libsfdo

cat >/etc/ld.so.conf.d/multi-seat-arch.conf <<'EOF'
/usr/local/lib
/usr/local/lib64
EOF
ldconfig

mkdir -p "$WORK"
cd "$WORK"

clone_or_checkout() {
  local url=$1 dir=$2 ref=${3:-} fallback=${4:-}

  if [[ -d "$dir/.git" ]]; then
    if ! git -C "$dir" fetch --all --tags --prune; then
      echo "Aviso: falha ao atualizar $dir pela origem; usando checkout local existente." >&2
    fi
    git -C "$dir" reset --hard
    git -C "$dir" clean -fdx
  else
    if ! git clone "$url" "$dir"; then
      if [[ -n "$fallback" ]]; then
        echo "Origem indisponível; tentando mirror: $fallback"
        git clone "$fallback" "$dir"
      else
        echo "Falha ao clonar $url e não há mirror configurado." >&2
        exit 11
      fi
    fi
  fi

  if [[ -n "$ref" ]]; then
    if ! git -C "$dir" checkout --force "$ref"; then
      echo "Falha ao selecionar ref $ref em $dir." >&2
      exit 12
    fi
  else
    local branch
    branch=$(git -C "$dir" symbolic-ref --short HEAD 2>/dev/null || true)
    if [[ -n "$branch" ]]; then
      if ! git -C "$dir" pull --ff-only origin "$branch"; then
        echo "Aviso: pull falhou em $dir; mantendo checkout local." >&2
      fi
    fi
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
build_make tomlc99

if [[ -e /usr/local/lib/pkgconfig && ! -d /usr/local/lib/pkgconfig ]]; then
  legacy_pkgconfig_backup="/usr/local/lib/pkgconfig.msa-legacy-$(date +%Y%m%d%H%M%S)"
  echo "Corrigindo instalação legada: /usr/local/lib/pkgconfig era um arquivo."
  mv /usr/local/lib/pkgconfig "$legacy_pkgconfig_backup"
  echo "Backup salvo em: $legacy_pkgconfig_backup"
fi
install -d /usr/local/lib/pkgconfig

cat >/usr/local/lib/pkgconfig/libtoml.pc <<'EOF'
prefix=/usr/local
exec_prefix=${prefix}
libdir=${exec_prefix}/lib
includedir=${prefix}/include

Name: libtoml
Description: TOML C99 library
Version: 1.0
Libs: -L${libdir} -ltoml
Cflags: -I${includedir}
EOF

if [[ -f /usr/local/lib/libtoml.so.1.0 && ! -e /usr/local/lib/libtoml.so ]]; then
  ln -s libtoml.so.1.0 /usr/local/lib/libtoml.so
fi
ldconfig

if ! pkg-config --exists libtoml; then
  echo "Falha: pkg-config não consegue localizar libtoml." >&2
  echo "PKG_CONFIG_PATH=$PKG_CONFIG_PATH" >&2
  cat /usr/local/lib/pkgconfig/libtoml.pc >&2 || true
  exit 6
fi
if ! printf '#include <toml.h>\nint main(void){return 0;}\n' \
  | cc -x c - -o /tmp/msa-libtoml-check $(pkg-config --cflags --libs libtoml); then
  echo "Falha: libtoml foi encontrada pelo pkg-config, mas não pode ser vinculada." >&2
  exit 7
fi
rm -f /tmp/msa-libtoml-check

echo "libtoml detectada: $(pkg-config --modversion libtoml)"

clone_or_checkout \
  https://gerrit.automotivelinux.org/gerrit/src/drm-lease-manager \
  drm-lease-manager \
  "" \
  https://github.com/AGLExport/drm-lease-manager.git
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
  exit 2
fi

python "$SCRIPT_DIR/patch_wlroots_input.py" \
  "$WORK/wlroots/backend/session/session.c"

grep -q 'getenv("DRM_LEASE")' wlroots/backend/session/session.c || {
  echo "Falha: patch DRM_LEASE não foi aplicado." >&2
  exit 3
}
grep -q 'Failed to directly open multiseat input' wlroots/backend/session/session.c || {
  echo "Falha: transformação de input direto não foi aplicada." >&2
  exit 10
}
if grep -q '\\t/\* Multi Seat Arch' wlroots/backend/session/session.c; then
  echo "Falha: transformação gerou escape literal \\t no C." >&2
  exit 13
fi
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
install -d /usr/local/share/multi-seat-arch
printf '%s\n' "$ENGINE_REV" >/usr/local/share/multi-seat-arch/engine-version

echo "Engine DRM lease instalada e validada."
echo "wlroots: $WLROOTS_REF / labwc: $LABWC_REF / engine: $ENGINE_REV"
