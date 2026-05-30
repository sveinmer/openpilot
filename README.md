<div align="center">

<h1>NAP-C3 (personal fork)</h1>

<p>
  <b>Personal NotAutopilot fork for one specific car.</b>
  <br>
  2014 Tesla Model S85 (pre-AP, tech non-P) · comma 3 · Tinkla Buddy IC · Comma Pedal · Tinkla Bosch radar.
</p>

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

</div>

---

## ⚠️ What this is

This is a **personal openpilot fork** for one specific Tesla. It is *not*
production-ready for other cars — tunes, LUTs, and CAN bit-layouts are
calibrated against a single 2014 S85 with specific retrofit modules.

- **Not affiliated with [comma.ai](https://comma.ai)** — comma 3 / openpilot
  are products of comma.ai
- **Not the [NotAutopilot organization](https://github.com/NotAutopilot)** —
  this is a downstream personal fork; for general pre-AP Tesla support go
  to [NotAutopilot/openpilot](https://github.com/NotAutopilot/openpilot)
- **Use at your own risk** — driver is responsible for all consequences

## Install on comma 3

On the comma 3 setup screen → **Custom Software** → **Other**:

| URL | Branch | Update cadence |
|---|---|---|
| `main.c3.cdma.no` | `main` | Stable — bumped after live-validation |
| `dev.c3.cdma.no`  | `dev`  | Rolling — synced from private after every live deploy |

URLs are HTTP 301-redirects to `installer.comma.ai/sveinmer/<branch>`.

## Hardware

| Component | Model |
|---|---|
| Vehicle | 2014 Tesla Model **S85** (Standard 85 kWh, tech-package, non-Performance) |
| Compute | comma **3** (F4 internal panda — **not comma 3X**) |
| Instrument cluster mod | Tinkla Buddy R2S 1.44 |
| Longitudinal control | Comma Pedal (throttle + regen via accel-cmd) |
| Forward sensing | Tinkla Bosch radar (GTW-emulated) |

## What works / what doesn't

✅ Lateral via EPAS + standalone panda safety
✅ Longitudinal via Comma Pedal (VirtualDAS cascade: jerk-limit → FF table → inner PID + grade comp)
✅ Lead-following with Bosch radar
✅ Buddy IC integration (lanes, lead vehicle, speed limit sign, gauge widgets)
✅ comma 3 F4 internal panda firmware (revived from upstream `bye bye f4`)

⚠️ ACC-radar-control under refinement — radar live, control loop being tuned
❌ **AEB not implemented** — pre-AP S85 has only regen braking (~50 kW), no friction-brake CAN path. Driver is the primary brake.
❌ Driver monitoring active but tuned for this driver's seating position

## Attribution

This fork stands on:

- **[commaai/openpilot](https://github.com/commaai/openpilot)** — the upstream driver-assistance platform
- **[NotAutopilot/openpilot](https://github.com/NotAutopilot/openpilot)** — pre-AP Tesla support, comma-pedal long-control architecture
- **[Tinkla project](https://tinkla.us/t/index)** — first proved openpilot works on pre-AP Teslas; CAN-stack, Buddy IC integration, Bosch radar GTW-emulation
- **[xnor-tech/openpilot](https://github.com/xnor-tech/openpilot)** — AP1 Model S support baseline
- **[MagZu/openpilot](https://github.com/MagZu/openpilot)** — feedforward-dominant pedal architecture reference
- **[FrogPilot](https://github.com/FrogAi/FrogPilot)** / OPGM Bolt — pedal tuning patterns

## Contributing

This is a personal fork — **PRs are not accepted here**. For community
contributions to pre-AP Tesla openpilot, see
[NotAutopilot/openpilot](https://github.com/NotAutopilot/openpilot).

## License

[MIT](LICENSE) (inherited from upstream commaai/openpilot).

## Sync mechanism

Private development happens at a private fork. Public mirror updated via
`scripts/sync_to_public.sh` after every live-validated deploy. The script
sanitizes:

- Deletes: `docs/`, `evidence/`, `.claude/`, build artifacts, proprietary firmware blobs
- Anonymizes: device IPs, dongle-ID, email, personal names
- Updates submodule pins to public mirrors
- Squashes to a single orphan commit (no private history exposed)

Submodule public mirrors:
- `opendbc_repo` → [sveinmer/nap-c3-opendbc](https://github.com/sveinmer/nap-c3-opendbc)
- `panda` → [sveinmer/nap-c3-panda](https://github.com/sveinmer/nap-c3-panda)
</content>
