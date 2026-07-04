# NAP Handover 2026-07-01 — IC lane-CURVES stuck (dyp diagnose)

**Symptom (Sveins ord):** IC-en tegner lane-linjene som **rette / stuck på én
tilfeldig sving**, uansett om veien svinger. **Kun kurvene** feiler —
skiltvisning, hastighet og MAX-widget rendrer korrekt. Kun på den **portede
NAP-forken** (sveinmer/openpilot main / MagZu-baseline). Regresjon fra
**fork-switch Ampera→Tesla 2026-06-24**.

**Status:** Rotårsak IKKE endelig isolert. Svært mye er ELIMINERT med bevis.
Sterkeste gjenværende spor: **panda-firmware-tilstanden** (public-flashbar-rot).

---

## Tidslinje (root-cause-vindu, bevist via reflog + connect-rute)

- **2026-06-20**: rute `00000104--c5a7306ffa` (public på connect) — **kurver VIRKET**.
  Kjørte openpilot **0.11.1**, commit **`f511dbb72`**, `TESLA_MODEL_S_PREAP`.
- **2026-06-23**: `git checkout main → StarPilot` (byttet til Ampera).
- **2026-06-24 21:57-58**: `checkout StarPilot → main` (byttet tilbake), landet på
  **`5c631347308`**, panda reflashet (panda.bin.signed mtime 21:57), `/data/backups`
  (StarPilot_auto) laget 21:58.
- **Nå**: stuck.

Reflog på C3 (`/data/openpilot`) bekrefter hele sekvensen.

---

## DEFINITIVT ELIMINERT (med bevis)

| Ledd | Bevis |
|---|---|
| openpilot **curve-kode** | Deployet `f511dbb72` (den EKSAKTE commiten fungerende rute kjørte på) + reboot → **fortsatt stuck**. Diff `f511dbb72..5c631347308` = **kun `pandad.py`** (DFU-recovery) + en test. |
| **hud_module/teslacan/DBC** | Byte-identisk med `b4538897` (der Svein bekreftet "lanes rendret") OG med Tinkla-gullstandarden (`/home/svein/repos/Tinkla`, 0.9.6 supercombo). Polyfit, `IC_LANE_SCALE=0.5`, clips, `create_lane_message`, DBC `DAS_virtualLaneC0-3` alt likt. |
| **driving-modell** | on-disk `driving_policy/vision.onnx` sha256 = committed LFS-OID. Metadata regenerert fra onnx = **identisk** (`15c8c1ad…`) → ikke stale. (mtime 2025-07-02 var villedende.) |
| **Buddy** | Rendrer signs/hastighet/MAX → MITM-pipeline engasjerer. Svein verifiserte OK. Buddy er låst til Tesla (ikke med til Ampera). |
| **kalibrering** | `CalibrationParams`: calStatus=calibrated, calPerc=100, rpy = roll 0.04° pitch −1.8° yaw −0.8° (normalt). |
| **panda TX/allowlist** | På dagens rute: 0x239 `sendcan`=`can`=600, alle `src=128` (transmittert, ikke rejected). Live `safety param=15` (teslaPreap, inkl. IC-bit) — **identisk** med fungerende rute. |
| **De dokumenterte MITM-trigger-feltene** (2026-05-25) | Alle korrekte på bussen NÅ: `0x659 adaptive_cruise=1`, `0x2B9 accState=4`/setSpeed nonzero, `0x488 steeringControlType=1`, `0x239 leftLaneExists=88%`. |

**Konklusjon:** curvC på bussen = polyfit av modellens `position`. Kode+modell
er verifisert identiske med fungerende tilstand. Curve-tweaking (scale/clip/
polyfit-domene) er BLINDSPOR — bekreftet, ikke rør det.

---

## HOVEDFUNN: public-flashbar panda-rot (det Claude endret)

Sveins krav: panda skal være flashbar fra public git-URL for alle.
`scripts/sync_submodules_to_public.sh:82`:
```bash
sync_submodule "panda" "nap-c3-dev-f4-rebuild" \
  "git@github.com:sveinmer/nap-c3-panda.git" "panda F4-revive for NAP nap-c3 —"
```
- Public panda-mirror synkes fra branch **`nap-c3-dev-f4-rebuild`** → panda **`02f19e33`** (F4-revive). `.gitmodules` peker panda → `sveinmer/nap-c3-panda` branch `main`.
- **Fungerende IC-firmware = `90387239` (Fase-7)** — bygget i worktree med patcher (Tesla-S `0x348` ignition, health v18, IC). Diff `90387239 ↔ 02f19e33` = **25 468 linjer** (F4-board-støtte, H7-config) — to fundamentalt ulike builds.

**Panda-firmware-mismatch (rotet):**
- version-fil `panda/board/obj/version` = `DEV-02f19e33-DEBUG`.
- on-disk `panda.bin.signed` + bootstub embedded = **`90387239`** (Fase-7).
- Live panda (beste evidens) = **`90387239`** (Fase-7; engasjering virker → krever 0x348 som kun Fase-7 har).
- swaglog nevner også `1a1f3f9c` (nap-c3-dev sin panda-submodul).
- pandad forventer `02f19e33` (version-fil) men live er `90387239` → mismatch → reflash-forsøk → "can't enter bootstub" → **`pandad: auto-recover via DFU`-commiten** (5c6313473). Dette ER switch-problemet Claude patchet.

**MEN uavklart:** Pandaen SENDER IC-frames uansett (allowlist fra opendbc,
ikke fra panda-board-koden). Så jeg kunne IKKE vanntett koble panda-mismatchen
til kurvene. IC-generator-spørsmålet (emitterte pandaen 0x239 selv?) kunne ikke
avgjøres — fungerende rute har kun qlog (ingen `can`-strøm; desimert).

---

## curvC-data: fungerende vs dagens (kan være vei-avhengig!)
- `00000104` (virker): 0x239 C2 **6% saturert**, C0 ±0.1 m (sentrert).
- dagens engasjert rute: C2 **28% saturert**, C0 −1.9…+0.5 m.
- ADVARSEL: ulike ruter/veier → forskjellen kan være vei-avhengig, ikke regresjon.
  Modellens `position` går ut til ~229 m (±87 m i fjern-enden); full-array
  polyfit korrelerer ~0.31-0.63 med nær-veien. Men Tinkla (fungerer) bruker
  IDENTISK kode → dette er sannsynligvis normalt, ikke bugen.

---

## ANBEFALTE NESTE STEG (prioritert)

1. **Rydd panda til ÉN komplett, konsistent firmware** (fikser BÅDE public-kravet OG er definitiv test):
   - Avklar live-versjon vanntett (query SPI-panda direkte når bilen er trygt parkert, ELLER pandad startup-swaglog).
   - Merge Fase-7-kapabilitet (`90387239`: 0x348-ignition, health v18, IC) inn i public-kilden `nap-c3-dev-f4-rebuild`, bygg én firmware, fiks version-pinnen (live == forventet, ingen DFU-churn), re-sync til public.
   - Flash rent → kjør → kurver tilbake = panda bekreftet; fortsatt stuck = openpilot-side.
2. **Hvis fortsatt stuck etter panda-rydding:** instrumenter modellens `position`-
   output LIVE (samme-vei A/B), da curvC=polyfit(position) og alt annet er
   eliminert. Sammenlign mot en fungerende-rute-rlog (krever full rlog — bruk
   Sveins connect user-JWT, ikke device-JWT som gir 403).

---

## NYTTIGE METODER / KOMMANDOER

- **Les rlog/qlog på C3:** `source /usr/local/venv/bin/activate; export PYTHONPATH=/data/openpilot/c3_third_party:/data/openpilot; cd /data/openpilot; python3 …` med `from openpilot.tools.lib.logreader import LogReader`.
- **Hent public connect-rute anonymt (uten JWT):** `curl -s "https://api.comma.ai/v1/route/<DONGLE>%7C<ROUTE>/files"` → `qlogs`/`logs` = signerte blob-URLer. **C3-ens internett mot comma er ustabilt** → last ned på Sveins WSL-maskin (`/home/svein/repos/...`) og scp til C3 for parsing. `logs` (rlog) er ofte tomme for public-ruter; `qlogs` finnes (desimert — mangler `can`).
- **device-JWT** (`from openpilot.common.api import Api; Api(dongle).get_token()`) gir **403** på rute-filer — trenger Sveins bruker-konto-JWT.
- **Panda-versjoner:** on-disk `strings panda/board/obj/panda.bin.signed | grep DEV-`; live via pandaStates (kun safety_mode/param) eller swaglog startup.
- Dongle: `2f2134836e3ab8f0`. C3: `ssh c3` → `comma@192.168.0.65`.

---

## C3-TILSTAND NÅ
- HEAD tilbake på **`5c631347308`** (main) — jeg reverterte f511dbb72-testen.
- Live panda = 90387239 (Fase-7). Ingen endringer gjort på panda-flash.
- Working-tree ren.

---

## SVEINS FEEDBACK DENNE SESJONEN (viktig for neste Claude)
- **Ikke gjett** (montering/kalibrering ble avvist uten bevis; "gammel Tinkla-kode"-
  antagelse var feil — Tinkla bruker moderne modelV2). Verifiser FØR du hevder.
- Curve/scale/lengde-tweaking = **blindspor**, bekreftet gjentatte ganger.
- Det er alt Claude-arbeid (ingen manuell Svein-injeksjon). "Injisert debug som
  ble renset" = Claude-endring ifm. switch-problem, sannsynlig panda.
