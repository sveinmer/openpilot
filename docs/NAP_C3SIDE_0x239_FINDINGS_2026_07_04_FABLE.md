# NAP C3-side 0x239 — funn 2026-07-04 (Fable, forts. fra UPSTREAM_GW-handover)

Fortsetter §5 i `NAP_HANDOVER_2026_07_04_KVELD_0x239_UPSTREAM_GW.md`. Delvis:
kodeanalyse + partiell live (bilen var AV → `noOutput`, ingen IC-strøm å fange).

## Nytt, konkret bevis: ethernet-0x239 er en FREMMED idle-frame (ikke vår)

Dekodet den konstante framen Buddy mottar vs openpilots faktiske output:

| Kilde | payload | byte1 = DAS_virtualLaneViewRange |
|---|---|---|
| **Buddy-inn (stuck, fra `gw`)** | `1001030b80011212` | **1** |
| openpilot `create_lane_message` | `6032…` (fungerende 06-20) | **50** (0x32) |

`create_lane_message` i `hud_module.py` sender **laneRange=50 hardkodet** — kan
ALDRI produsere range=1. Panda-cachen re-emitterer openpilots bytes (→ range=50),
og `preap_ic_reset_state` gir bytes=0 (→ range=0). **Ingen sti i openpilot/panda-
stacken produserer range=1.** → Framen `gw` sender til Buddy stammer IKKE fra vår
stack; den er en fremmed/idle DAS_lanes-default (Tesla-systemets egen tomme frame).

**Reframe:** problemet er ikke «openpilot sender feil kurver» eller «panda-cache
stale» (begge ville gitt range=50). Det er at **openpilots ekte 0x239 (range=50)
ikke når Tesla-ethernet/IC-en lenger**, så en fremmed idle-default (range=1) fyller
0x239-sloten som Buddy videresender. På 06-20 (virket) NÅDDE range=50 IC-en.

## Panda IC-generator: koden er sunn (lest i tesla_preap.h)
- `preap_ic_capture_tx` (L412) fanger openpilots 0x239 UBETINGET når
  `preap_has_ic_integration` er på (tx_hook L806-807). Ingen bit-gate.
- `preap_ic_send_messages` (L490) re-emitterer 0x239 fra cache på GTW_status
  (0x348)-tick, 10 Hz, `can_send(bus 0)`. Emitterer kun hvis `cache.valid`.
- 0x239 er i TX-whitelist (bus 0) og cache-adr[0]. Alt korrekt.
→ Panda re-emit ville vært range=50 (openpilots verdi). Bekrefter at range=1
  ikke er panda-generatoren.

## `gw` er IKKE comma-boksen
C3 (192.168.0.65) har **ingen** 192.168.90.x-grensesnitt/rute, ingen MAC
`00:00:a7:01:02:03`, ingen prosess på port 20101/20201/31415, ingen EtherCAN-
bridge-prosess. → `gw` (192.168.90.102) er en SEPARAT enhet på Tesla-ethernet.
Hovedkandidat: **Teslas egen gateway (GTW)** som natively bygger CAN↔ethernet.
Den forwarder openpilots 0x659 (varierer) men leverer 0x239 som konstant idle —
dvs. behandler 0x239 annerledes (egen native idle-DAS_lanes vs vår CAN-0x239).

## DECISIVE neste test (KREVER bil PÅ / kjørende)
Bilen var av denne økten (`safetyModel: noOutput`, param 0) → ingen live-IC.
Kjør samtidig, mens bilen er på:
1. **CAN-side 0x239** (cereal `can`/`sendcan` på C3): forvent range=50, varierer
   — bevis at openpilot fortsatt sender ekte lanes på CAN.
   Verktøy: `scripts/nap_ic_curve_analysis/` + `scratchpad/c3_live_0x239.py`.
2. **Ethernet-side 0x239** (Buddy eth0-inn, live-sesjonens
   `onroad_0x239_source.py`): range=1, konstant.
3. Divergens (CAN=50 varierer vs ethernet=1 konstant) BEKREFTER at bruddet er i
   CAN→ethernet-broen (`gw`/Tesla GTW), ikke openpilot-encoding.

**Deretter:** finn hvorfor `gw` slutter å bygge openpilots 0x239 til ethernet
etter bil-bytte, mens 0x659 fortsatt bygges. Sammenlign 0x239 vs 0x659 sin
CAN→ethernet-vei i GTW/bridge-konfig. Spørsmål: emitterer Tesla-GTW sin EGEN
0x239 (idle) som kolliderer med / overstyrer vår, og gjorde den ikke det før
bil-byttet (annen GTW-state/config)?

## Advarsel til neste økt
Ikke gjenta «range=50 CAN varierer» fra tidligere økter som bevis alene — det er
CAN-siden. Poenget er DIVERGENSEN mot ethernet-siden (range=1), som må måles
SAMTIDIG live. Bilen må være på.
