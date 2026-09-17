# Code review — 2026-09-17

Branch reviewed: `experimental/plasma-drm-lease-v1`

This document records the current technical debt, risk level and the order in which it should be addressed. The first stabilization phase deliberately prefers behavior-preserving changes over broad rewrites because boot, DRM leasing, login and restore paths can leave the host without a graphical session if they regress.

## Priority findings

1. **High — runtime patch stack**
   The final backend behavior is assembled by `runtime_patch.py` through `runtime_patch_v14.py`. Import order is therefore part of the runtime contract and the effective implementation of functions such as `activate_now`, `restore_now` and `sync_devices_now` is distributed across many files. Goal: converge on one canonical runtime implementation. First safe step: centralize patch registration/order in one module, add regression coverage, then fold patches into canonical modules incrementally.

2. **High — autostart failure handler is incomplete**
   `disable_after_boot_failure()` exists, but boot failures that occur before or outside the backend rollback path can still leave the current boot without a graphical recovery. Goal: every boot failure must disable autostart for the next boot and trigger recovery for the current boot.

3. **High — no external boot watchdog/recovery unit**
   The boot service has a timeout, but timeout/failure recovery must not depend on the same process that failed. Goal: use an independent systemd `OnFailure=` recovery service that returns the host to normal graphical mode and makes the next boot safe.

4. **High — missing regression tests for critical recent paths**
   Coverage is weakest around autostart, SDDM/Atrium bridge integration, runtime patch composition and recent restore patches. Goal: add focused tests around generated systemd units, boot recovery dispatch, runtime composition and SDDM protocol helpers.

5. **High — CI does not exercise an Arch environment**
   Ubuntu CI is useful for Python portability but does not represent the target platform. Goal: keep the fast Ubuntu matrix and add an Arch Linux smoke job for package installation, imports, compile checks and unit tests that do not require real DRM hardware.

7. **Medium/high — multiple active generations of the same component**
   `gui.py` through `gui_v4.py`, multiple display/session modules and many runtime patch generations make the active architecture hard to follow. Goal: establish canonical public entry modules first, then migrate behavior into them and retire versioned implementation files only after coverage proves equivalence.

## Remaining findings

6. SDDM bridge relies on SDDM's internal greeter protocol; add explicit compatibility/version checks.
8. GUI inheritance chain is too deep; separate UI, state and privileged operations.
9. Installer uses `pip --break-system-packages`; move toward a package/isolated installation model.
10. Installer likely carries legacy LXQt/XFCE dependencies; audit and remove unused packages.
11. `Seat.user` remains mandatory even though dynamic login ignores it.
12. Configuration schema is too small for audio/Bluetooth/login/boot policies.
13. Persistent configuration, runtime state and markers are spread across `/etc`, `/var/lib` and `/run` without a formal layout contract.
14. Some recovery paths intentionally swallow exceptions; these should at least be journaled.
15. No explicit lifecycle state machine exists for NORMAL/STARTING/MULTISEAT/RESTORING/FAILED.
16. Start/restore idempotency should be tested as a contract.
17. Bluetooth audio ownership is reconstructed from node names instead of storing a canonical BlueZ identity.
18. WirePlumber configuration should be guarded by a supported-version check.
19. KWin/Atrium source patches should be tied to exact upstream revisions and validated in CI.
20. `doctor` should be expanded into a complete diagnostics bundle command.
21. Atomic configuration writes should use `fsync` for boot-critical durability.
22. Add lint/type/shell checks such as Ruff, Pyright/Mypy and ShellCheck.
23. Project version is duplicated between `pyproject.toml` and `__init__.py`.
24. README/docs lag behind the current KDE/SDDM/DRM-lease architecture.

## Stabilization phase 1

The first implementation pass targets findings **1, 2, 3, 4, 5 and 7** with the following safety rules:

- Preserve the proven DRM/KWin/Atrium execution order.
- Do not alter KWin lease semantics in this phase.
- Move orchestration behind canonical modules before deleting legacy implementations.
- Make boot recovery independent of the failing boot service.
- Add tests before retiring old code paths.
- Keep normal desktop recovery available after every failure path.

## Exit criteria for phase 1

- Runtime patch ordering has one canonical registration point and is covered by tests.
- Autostart has an external `OnFailure=` recovery service.
- A failed or timed-out multiseat boot restores graphical mode in the current boot and disables multiseat autostart for the next boot.
- CI contains both the existing Ubuntu checks and an Arch smoke job.
- Canonical public entry modules are documented so versioned modules can be retired incrementally.
- No KWin rebuild is required by these refactors.
