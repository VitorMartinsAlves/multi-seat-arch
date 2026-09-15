#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || {
  echo "Execute com sudo/root." >&2
  exit 1
}

TARGET_USER=${SUDO_USER:-${1:-}}
if [[ -z "$TARGET_USER" || "$TARGET_USER" == "root" ]]; then
  echo "Não foi possível determinar o usuário desktop para validar user namespaces." >&2
  exit 2
fi

SYSCTL_FILE=/etc/sysctl.d/99-multi-seat-arch-userns.conf
TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT

{
  echo "# Managed by multi-seat-arch. Required by Steam pressure-vessel/bubblewrap"
  echo "# and Chromium-family sandboxes on kernels that restrict unprivileged user namespaces."

  if [[ -e /proc/sys/user/max_user_namespaces ]]; then
    current=$(cat /proc/sys/user/max_user_namespaces 2>/dev/null || echo 0)
    if [[ "$current" =~ ^[0-9]+$ ]] && (( current < 15000 )); then
      echo "user.max_user_namespaces = 15000"
    fi
  fi

  if [[ -e /proc/sys/kernel/unprivileged_userns_clone ]]; then
    echo "kernel.unprivileged_userns_clone = 1"
  fi

  # Modern AppArmor can block userns even when unprivileged_userns_clone=1.
  # Disable only AppArmor's user-namespace mediation knobs, not AppArmor itself.
  if [[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]]; then
    echo "kernel.apparmor_restrict_unprivileged_userns = 0"
  fi
  if [[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_unconfined ]]; then
    echo "kernel.apparmor_restrict_unprivileged_unconfined = 0"
  fi
} >"$TMP"

if [[ -s "$TMP" ]]; then
  install -Dm644 "$TMP" "$SYSCTL_FILE"
  sysctl -p "$SYSCTL_FILE" >/dev/null
fi

print_diag() {
  echo "Diagnóstico de user namespaces:" >&2
  for key in \
    user.max_user_namespaces \
    kernel.unprivileged_userns_clone \
    kernel.apparmor_restrict_unprivileged_userns \
    kernel.apparmor_restrict_unprivileged_unconfined; do
    sysctl "$key" 2>/dev/null || true
  done >&2
}

# Validate the capability itself instead of assuming a distro-specific knob is enough.
if ! runuser -u "$TARGET_USER" -- unshare --user --map-root-user /usr/bin/true; then
  echo "Falha: criação de user namespace continua bloqueada para $TARGET_USER." >&2
  print_diag
  exit 3
fi

# Steam pressure-vessel uses bubblewrap. This catches LSM/mount restrictions that
# a bare unshare test does not catch and is also representative of Chromium sandboxes.
if command -v bwrap >/dev/null 2>&1; then
  if ! runuser -u "$TARGET_USER" -- bwrap \
      --unshare-user --unshare-pid --unshare-ipc --unshare-uts \
      --ro-bind /usr /usr --proc /proc --dev /dev \
      /usr/bin/true; then
    echo "Falha: bubblewrap ainda não consegue criar o sandbox para $TARGET_USER." >&2
    print_diag
    exit 4
  fi
fi

echo "User namespaces e bubblewrap validados para $TARGET_USER."
