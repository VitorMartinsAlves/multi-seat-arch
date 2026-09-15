from __future__ import annotations

import json
from pathlib import Path
from types import ModuleType

ACL_STATE = Path("/run/multi-seat-arch/input-acls.json")


def install(backend: ModuleType) -> None:
    """Prepare evdev access for DRM-lease multiseat compositors.

    Real-hardware testing on systemd 261 showed that logind creates the correct
    custom seats and sessions, but open_device() can still reject input access
    because the transient compositor session has no conventional active VT.
    The wlroots engine patch opens only /dev/input/event* directly when
    DRM_LEASE is active. Here we grant each configured seat user an ACL only on
    the event nodes assigned to that seat, while keeping logind/XDG_SEAT for
    libinput's seat filtering. Grants live only for the multiseat runtime and are
    explicitly revoked on restore/rollback.
    """
    if getattr(backend, "_msa_runtime_patch_v4_installed", False):
        return

    previous_activate = backend.activate_now
    previous_systemd_run = backend._systemd_run
    previous_flush_inputs = backend.flush_inputs

    def _save_grants(grants: set[tuple[str, str]]) -> None:
        ACL_STATE.parent.mkdir(parents=True, exist_ok=True)
        ACL_STATE.write_text(
            json.dumps(sorted([{"user": user, "event": event} for user, event in grants], key=lambda item: (item["user"], item["event"]))),
            encoding="utf-8",
        )

    def _load_grants() -> set[tuple[str, str]]:
        try:
            data = json.loads(ACL_STATE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return set()
        return {
            (str(item.get("user", "")), str(item.get("event", "")))
            for item in data
            if item.get("user") and item.get("event")
        }

    def revoke_input_acls() -> None:
        if backend.command_exists("setfacl"):
            for user, event in _load_grants():
                if Path(event).exists():
                    backend._run(["setfacl", "-x", f"u:{user}", event], check=False)
        ACL_STATE.unlink(missing_ok=True)

    def flush_inputs() -> None:
        revoke_input_acls()
        previous_flush_inputs()

    def _set_acl(user: str, event: str, grants: set[tuple[str, str]]) -> None:
        if not Path(event).exists():
            raise RuntimeError(f"Evento de input não existe: {event}")
        result = backend._run(["setfacl", "-m", f"u:{user}:rw", event], check=False)
        if result.returncode:
            raise RuntimeError(
                f"Falha ao liberar {event} para {user}: {result.stdout.strip()}"
            )
        grants.add((user, event))
        _save_grants(grants)

    def _event_children(parent: str) -> list[str]:
        return [str(path) for path in sorted(Path(parent).glob("event*")) if path.is_dir()]

    def grant_input_acls(config) -> None:
        if not backend.command_exists("setfacl"):
            raise RuntimeError("setfacl não encontrado. Instale o pacote acl.")

        revoke_input_acls()
        users = {seat.name: seat.user for seat in backend.active_seats(config)}
        grants: set[tuple[str, str]] = set()

        # Current ASTER-like device rules. Grouped USB devices still resolve to
        # individual evdev functions, so every configured event gets its own ACL.
        for rule, device in backend.resolve_device_rules(config):
            if rule.mode != "seat" or not rule.seat:
                continue
            user = users.get(rule.seat)
            if not user:
                continue
            pair = (user, device.event)
            if pair not in grants:
                _set_acl(user, device.event, grants)

        # Backward-compatible explicit inputN assignments.
        for seat in backend.active_seats(config):
            for parent in seat.inputs:
                for syspath in _event_children(parent):
                    event = f"/dev/input/{Path(syspath).name}"
                    pair = (seat.user, event)
                    if pair not in grants and Path(event).exists():
                        _set_acl(seat.user, event, grants)

        # Shared uinput clones are created during sync_devices_now. Their ready
        # files expose the virtual inputN parents; grant the matching seat user
        # access to each generated event node too.
        for ready in backend.READY_DIR.glob("*.json"):
            try:
                data = json.loads(ready.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for runtime, parent in (data.get("virtual") or {}).items():
                target = next(
                    (
                        seat
                        for seat in backend.active_seats(config)
                        if backend.runtime_seat_name(seat) == runtime
                    ),
                    None,
                )
                if not target:
                    continue
                for syspath in _event_children(parent):
                    event = f"/dev/input/{Path(syspath).name}"
                    pair = (target.user, event)
                    if pair not in grants and Path(event).exists():
                        _set_acl(target.user, event, grants)

        if not grants:
            raise RuntimeError("Nenhum event node foi liberado para os seats.")

    def systemd_run(unit: str, command: list[str], *, uid=None, env=None, properties=None, no_block=False) -> None:
        patched_env = dict(env or {})
        if unit.startswith("msa-seat-"):
            # Use the real custom logind seat. Forcing seatd made Labwc exit
            # before creating a Wayland socket on the target Ice Lake notebook.
            patched_env["LIBSEAT_BACKEND"] = "logind"
            patched_env["SEATD_VTBOUND"] = "0"
            # Never mask a missing input backend; a failure should roll back.
            patched_env.pop("WLR_LIBINPUT_NO_DEVICES", None)
        previous_systemd_run(
            unit,
            command,
            uid=uid,
            env=patched_env,
            properties=properties,
            no_block=no_block,
        )

    def activate(config) -> None:
        original_sync = backend.sync_devices_now

        def sync_and_acl(cfg) -> None:
            original_sync(cfg)
            grant_input_acls(cfg)

        backend.sync_devices_now = sync_and_acl
        try:
            previous_activate(config)
        finally:
            backend.sync_devices_now = original_sync

    backend.flush_inputs = flush_inputs
    backend._systemd_run = systemd_run
    backend.activate_now = activate
    backend._msa_runtime_patch_v4_installed = True
