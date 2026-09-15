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

  # AppArmor 4/modern distro kernels can deny userns even when
  # kernel.unprivileged_userns_clone=1. Disable only the user-namespace
  # mediation knobs when those sysctls exist; AppArmor itself stays enabled.
  if [[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]]; then
    echo "kernel.apparmor_restrict_unprivileged_userns = 0"
  fi
  if [[ -e /proc/sys/kernel/apparmor_restrict_unprivileged_unconfined ]]; then
    echo "kernel.apparmor_restrict_unprivileged_unconfined = 0"
  fi
} >"$TMP"

if [[ -s "$TMP" ]]; then
  install -Dm644 "$TMP" "$SYSCTL_FILE"
  sysctl --system >/dev/null
fi

# Validate the capability Steam/Chromium actually need instead of trusting one
# distro-specific sysctl name. This catches AppArmor/LSM restrictions too.
if ! runuser -u "$TARGET_USER" -- unshare --user --map-root-user /usr/bin/true; then
  echo "Falha: user namespaces continuam bloqueados para $TARGET_USER." >&2
  echo "Diagnóstico:" >&2
  for key in \
    user.max_user_namespaces \
    kernel.unprivileged_userns_clone \
    kernel.apparmor_restrict_unprivileged_userns \
    kernel.apparmor_restrict_unprivileged_unconfined; do
    sysctl "$key" 2>/dev/null || true
  done >&2
  exit 3
fi

echo "User namespaces validados para $TARGET_USER."
