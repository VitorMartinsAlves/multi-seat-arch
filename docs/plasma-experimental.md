# Plasma/KWin single-GPU multiseat experiment

This branch keeps the proven `drm-lease-manager` topology, but replaces Labwc/LXQt with an isolated patched KWin plus Plasma Shell per seat.

## Architecture

```text
Intel GPU
  |
  +-- drm-lease-manager
       +-- card1-HDMI-A-1 lease -> patched KWin #1 -> Plasma #1
       +-- card1-eDP-1 lease     -> patched KWin #2 -> Plasma #2
```

The system KWin package is **not replaced**. `scripts/build-kwin-plasma.sh` builds the exact installed KWin version, patches only `LogindSession::openRestricted()` for primary DRM nodes, and stages the result under `/opt/multi-seat-arch/kwin-plasma`.

Input still comes from the existing real logind seats. DRM access for KWin comes from `libdlmclient`; render nodes and evdev keep their normal logind paths.

## Build and enable

From this experimental branch:

```bash
sudo multi-seat-arch restore
bash scripts/install.sh
bash scripts/build-kwin-plasma.sh
sudo multi-seat-arch plasma-enable
multi-seat-arch doctor
sudo multi-seat-arch start
```

The KWin build is intentionally separate because it can take several minutes.

## Return to the stable Labwc backend

```bash
sudo multi-seat-arch restore
sudo multi-seat-arch plasma-disable
sudo multi-seat-arch start
```

Or simply reboot and run `restore` before changing the compositor again.

## What the KWin patch does

When `KWIN_DRM_LEASE=<connector>` is present and KWin asks logind to open `/dev/dri/card*`, the patched session backend requests that named lease from `drm-lease-manager`, duplicates the leased fd and returns it to KWin. Input devices and render nodes are not intercepted.

When KWin closes that fd, the corresponding `dlm_lease` handle is released. Without `KWIN_DRM_LEASE`, KWin follows its normal upstream logind path.

## Expected first-test limitations

This is real experimental compositor work, not a theme layer. The first hardware test should focus on whether both KWin instances create Wayland sockets and enumerate only their leased output. Plasma Shell is started after each KWin socket appears. If activation fails, the existing rollback still returns to `graphical.target` and writes `/var/log/multi-seat-arch-last-error.log`.
