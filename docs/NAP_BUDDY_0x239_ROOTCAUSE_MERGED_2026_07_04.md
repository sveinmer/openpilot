> # ⚠️ SUPERSEDED 2026-07-04 (kveld) — KONKLUSJONEN UNDER ER MOTBEVIST
> Se `docs/NAP_HANDOVER_2026_07_04_KVELD_0x239_UPSTREAM_GW.md`.
> Live-bevis: (1) `DAS_fakeDasReceived` lest i Buddys /proc/PID/mem = **1**, ikke 0.
> (2) v1.49-binæren viser at latchen settes UBETINGET (bit-testen gater den ikke).
> (3) 0x239 ankommer Buddys chassis-inngang (eth0:20101) ALLEREDE konstant, fra
> kilden `gw` (192.168.90.102) — Buddy er en ren videresender. Fixen er oppstrøms
> (panda IC-emit-cache / C3 EtherCAN), IKKE Buddy og IKKE 0x659-latchen.

# NAP Buddy 0x239 — samlet root-cause (to uavhengige spor konvergerer) 2026-07-04

Forener **live-sesjonen ved bilen** (Sonnet, pushet til public `main`
`79ef65196`, `docs/NAP_BUDDY_0x239_FINDINGS_2026_07_04.md`) med **offline
binær-reversering** (denne sesjonen, Fable, av nedlastet firmware-image i repo
`/home/svein/repos/tinkla-buddy-firmware`). De to ble gjort uavhengig og lander
på nøyaktig samme mekanisme.

## Konklusjon (binær-bekreftet)

Buddy erstatter openpilots 0x239 DAS_lanes med en konstant fallback-frame
(`1001030b00011212`, range=1/ingen kurver) fordi **`DAS_fakeDasReceived` er
`false` i Buddys runtime etter bil-byttet**. Alle andre DAS-frames
(0x399/0x389/0x309/0x659/0x2B9) passerer uendret. Fixen er på Buddy-siden.

## Presis gate-logikk (fra `tinklaBuddy`-disassembly, v1.44-arkiv; symboler
identiske med live v1.49)

**`process_DI_state`** (@0x406a80) emitterer IC-0x239, trigget av bilens
DI_state-melding, gated slik:
```
ldr w4, [OPIntegration]      ; /opt/tinkla/settings/tinklaOPIntegration
cmp w4, #1
b.eq check_fakedas           ; OP-integrasjon PÅ (Sveins boks: =1 ✓)
...                          ; ellers "ic integration for fakeDAS not enabled, do nothing"
check_fakedas:
ldr w4, [DAS_fakeDasReceived] ; global @0x4d3c0c
cbz w4, not_received          ; ==0 → "did not receive fakeDas yet, do nothing" → fallback
... bygg ekte 0x239 m/ lane C0-C3 ...
```
→ Med `OPIntegration=1` men `DAS_fakeDasReceived=0` tar den **"did not receive
fakeDas yet"-grenen** = den konstante fallback-framen Svein ser. Bekreftet: begge
"do nothing"-strengene refereres kun av `process_DI_state`.

**`DAS_fakeDasReceived` settes til 1 KUN i `process_fake_das`** (@0x406d98,
offset 0x11c): når en innkommende fakeDAS-frame ankommer OG en bit-test på
frame-payloaden passerer (`tbz` på en payload-byte). Det er en **latch**
(`cbnz` hopper over re-init når allerede satt) → starter `false` ved
Buddy-boot/bil-bytte og må re-trigges av en kvalifiserende fakeDAS-frame.

## Hva dette betyr for fix

1. **`restart tinklaBuddy` alene er ikke garantert nok** — det NULLSTILLER
   latchen til false; den må så re-trigges av en fakeDAS-frame som passerer
   bit-testen. Hjelper kun hvis openpilot faktisk sender en kvalifiserende frame.
2. **Åpent spørsmål (avgjør fix):** sender openpilots `create_fake_DAS_msg`
   (0x659) fortsatt frame-en/bit-en som `process_fake_das` latcher på? Hvis
   bil-byttet endret et felt i 0x659 slik at latch-biten ikke lenger settes,
   er DET openpilot-sidens bidrag — og kobler til acc-state/enabled-gate-
   sporet fra 07-02. Live-sesjonen så 0x659 = 412 unike payloads (varierer),
   så frame-en sendes; spørsmålet er om latch-biten er satt.
3. **`gtw_dashw`** på Sveins boks = `0` (live). `process_DI_state`/andre bruker
   `GTW_dasHw` (@0x4d2094) videre nedstrøms. Verifiser riktig verdi for preAP
   Model S.

## Presis diagnostikk neste bil-økt (WiFi tinklaAP, parkert)
1. **Disassembler Sveins FAKTISKE v1.49-binær** (`scp pi@10.5.5.1:/opt/tinkla/bin/tinklaBuddy`)
   og kjør `scratchpad/xref2.py DAS_fakeDasReceived` + `disas.py process_fake_das`
   → les den EKSAKTE latch-biten (offset kan avvike v1.44→v1.49). Map biten til
   `create_fake_DAS_msg`-byte i `teslacan.py`.
2. **Live-sjekk latchen:** les Buddys runtime-state (hvis eksponert), eller
   send en 0x659 med latch-biten tvunget satt via t5-inject til eth0-IP (ikke
   loopback — live-sesjonens T5 gikk til 127.0.0.1 og traff kanskje ikke
   listener) og se om 0x239 på eth1 begynner å variere.
3. Hvis latch-biten IKKE lenger settes av openpilot → liten openpilot-fix i
   `hud_module.py`/`teslacan.py` (sett riktig bit i 0x659). Hvis den settes men
   Buddy fortsatt ikke latcher → Buddy-intern (gtw_dashw/carConfig-avhengighet).

## Verktøy (denne sesjonen)
- Firmware-arkiv: `/home/svein/repos/tinkla-buddy-firmware` (img.gz + ekstrahert
  `/opt/tinkla` + README). Binær er ustrippet aarch64 m/ debug_info.
- `scratchpad/`: `disas.py` (symbol-disas m/ strengoppløsning),
  `xref2.py` (global read/write-xref), `findstr.py` (streng→funksjon).
- Nøkkelsymboler: `process_DI_state`, `process_fake_das`, `process_packet`
  (dispatcher, arb-id strcmp), globals `DAS_fakeDasReceived`@0x4d3c0c,
  `GTW_dasHw`@0x4d2094, `real_DAS_enabled`@0x4d3bd0.
