from __future__ import annotations

from types import ModuleType


def install(backend: ModuleType) -> None:
    """Keep established DRM-lease seats stable after startup.

    On the target Ice Lake notebook, both Labwc seats start and accept input,
    then the initial hotplug watcher pass calls sync_devices_now(). That routine
    flushes logind/udev device assignments and both compositors exit cleanly a
    few seconds later. Until live re-routing is made differential (without
    loginctl flush-devices / udev seat teardown), do not auto-start the watcher.

    Manual start/restore and the initial activation routing remain unchanged.
    """
    if getattr(backend, "_msa_runtime_patch_v5_installed", False):
        return

    def stable_hotplug_watcher() -> None:
        # Intentionally disabled for active DRM-lease seats. A full live resync
        # tears down the custom logind seats and invalidates compositor input.
        return None

    backend._start_hotplug_watcher = stable_hotplug_watcher
    backend._msa_runtime_patch_v5_installed = True
