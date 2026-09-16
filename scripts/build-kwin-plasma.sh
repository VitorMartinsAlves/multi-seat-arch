#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
  echo "Execute como usuário normal; o script usa sudo apenas para pacman/install." >&2
  exit 1
fi

REPO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
WORK=${WORK:-$HOME/.cache/multi-seat-arch/kwin-plasma}
SRC="$WORK/kwin"
BUILD="$WORK/build"
STAGE="$WORK/stage"
PREFIX=/opt/multi-seat-arch/kwin-plasma

if ! pacman -Q kwin >/dev/null 2>&1; then
  echo "KWin não está instalado; instale o Plasma/KWin primeiro." >&2
  exit 2
fi

pkgver=$(pacman -Q kwin | awk '{print $2}')
kwin_ver=$(printf '%s' "$pkgver" | sed -E 's/-[0-9]+(\.[0-9]+)*$//')
tag="v${kwin_ver}"

echo "KWin instalado: $pkgver"
echo "Fonte experimental: KDE/kwin $tag"

sudo pacman -S --needed --noconfirm \
  git base-devel cmake ninja extra-cmake-modules pkgconf python \
  kdoctools krunner plasma-wayland-protocols vulkan-headers \
  wayland-protocols xorg-xwayland plasma-workspace

if [[ ! -f /usr/include/vulkan/vulkan.h ]]; then
  echo "Falha: headers Vulkan ausentes mesmo após instalar vulkan-headers." >&2
  echo "Verifique o pacote com: pacman -Ql vulkan-headers" >&2
  exit 3
fi

export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:/usr/local/lib64/pkgconfig:${PKG_CONFIG_PATH:-}"
if ! pkg-config --exists libdlmclient; then
  echo "libdlmclient não foi encontrada. Rode primeiro: bash scripts/install.sh" >&2
  exit 4
fi

mkdir -p "$WORK"
if [[ -d "$SRC/.git" ]]; then
  git -C "$SRC" fetch --tags --force origin
  git -C "$SRC" reset --hard
  git -C "$SRC" clean -fdx
  git -C "$SRC" checkout --force "$tag"
else
  git clone --depth 1 --branch "$tag" https://github.com/KDE/kwin.git "$SRC"
fi

python "$REPO_DIR/scripts/patch-kwin-drm-lease.py" "$SRC"

grep -q 'MULTI_SEAT_ARCH_DRM_LEASE' "$SRC/src/core/session_logind.cpp" || {
  echo "Falha: patch de lease no LogindSession não foi aplicado." >&2
  exit 5
}
grep -q 'MULTI_SEAT_ARCH_DRMDEVICE_LEASE_FD' "$SRC/src/core/drmdevice.cpp" || {
  echo "Falha: patch de lease no DrmDevice não foi aplicado." >&2
  exit 5
}

rm -rf "$BUILD" "$STAGE"
cmake -S "$SRC" -B "$BUILD" -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX=/usr \
  -DBUILD_TESTING=OFF \
  -DKWIN_BUILD_TESTING=OFF

cmake --build "$BUILD" -j"$(nproc)"
DESTDIR="$STAGE" cmake --install "$BUILD"

for binary in kwin_wayland kwin_wayland_wrapper; do
  [[ -x "$STAGE/usr/bin/$binary" ]] || {
    echo "Falha: $binary não apareceu no staging." >&2
    exit 6
  }
done

sudo rm -rf "$PREFIX"
sudo install -d "$PREFIX"
sudo cp -a "$STAGE/usr" "$PREFIX/usr"

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

sudo install -d /usr/local/share/multi-seat-arch
printf '%s\n' "$kwin_ver" | sudo tee /usr/local/share/multi-seat-arch/kwin-plasma-version >/dev/null

missing=$(env LD_LIBRARY_PATH="$PREFIX/usr/lib:${LD_LIBRARY_PATH:-}" ldd "$PREFIX/usr/bin/kwin_wayland" | grep 'not found' || true)
if [[ -z "$missing" ]]; then
  echo "KWin experimental instalado em $PREFIX"
  echo "Wrapper: /usr/local/bin/kwin-wayland-msa"
  echo "Versão: $kwin_ver"
  echo "Patch externo validado em LogindSession + DrmDevice."
else
  echo "Falha: bibliotecas ausentes no KWin experimental:" >&2
  echo "$missing" >&2
  exit 7
fi
