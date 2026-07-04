# NAP Buddy 0x239 DAS_lanes — Findings 2026-07-04

**Status: Root cause identifisert. Fix er på Buddy-siden.**

## Bakgrunn

Kurver vises ikke på Tesla IC via Tinkla Buddy. Fungerte på Tesla → byttet til
Ampera → byttet tilbake til Tesla → kurver sluttet å virke.

Tidligere arbeid (buddy_sprint 2026-05-25) forberedte test-scripts, men selve
kjøringen og analyse ble fullført i denne sesjonen.

## Bevist kausal kjede

### C3 / openpilot — KORREKT

- openpilot sender 0x239 DAS_lanes via `sendcan` (cereal) ved 10 Hz
- Payload varierer: `6032647d...` (range=50, laneWidth=3.875m) — matcher
  `create_lane_message()` i `hud_module.py`
- Panda TX-echo på CAN bus 0 (src=128): 10 unike payloads — panda sender korrekt
- Panda config: safety_model=37 (teslaPreap ✓), safety_param=15 = 0b1111
  (PREAP_FLAG_IC_INTEGRATION = 8 satt ✓)
- Params korrekte: NAPForcePreAP=1, NAPTinklaICIntegration=1,
  fingerprint=TESLA_MODEL_S_PREAP

### Buddy eth1 (IC-siden) — FEIL

- Buddy leverer konstant `1001030b00011212` til IC på eth1
- Denne framen finnes IKKE på fysisk CAN — ikke fra panda, ikke fra bilen
- Dekoda: range=1, C0=-3.395 (ingen kurver synlig på IC)
- Teller (byte 7 øvre nibble) = 1 alltid — ingen rotasjon → ikke panda IC-emitter
- Bytes 2-3 = `030b` — samme signatur som buddy_sprint 2026-05-25 konstant
  `7001030b80101611`

### Alle andre DAS-frames — KORREKT

0x399=37 unike, 0x389, 0x309, 0x659=412 unike, 0x2B9=138 unike — passerer alle
gjennom Buddy og varierer. Kun 0x239 erstattes.

### T5 inject-bevis

Sendte 10× `DEADBEEF11223344` EtherCAN-frames til Buddy 127.0.0.1:20101
(arb=0x239) mens eth1 ble lyttet på med AF_PACKET sniffer.

**Resultat:** DEADBEEF dukket aldri opp på eth1. Konstant `1001030b00011212`
fortsatte uendret. Buddy har en aktiv 0x239-generator som overrider alt.

## Tinkla Buddy binary-analyse

Binary: `/opt/tinkla/bin/tinklaBuddy` (1.4 MB, v1.49, kjørt som root siden Apr 24)

### Nøkkel-strings fra binary

```
"ic integration for fakeDAS not enabled, do nothing"   ← tinklaOPIntegration=0
"did not receive fakeDas yet, do nothing"              ← DAS_fakeDasReceived=false
```

Interne state-variabler: `DAS_fakeDasReceived`, `real_DAS_enabled`,
`GTW_carConfig*_received`

### Settings på Buddy

| Setting | Verdi | Forventet |
|---|---|---|
| tinklaOPIntegration | 1 | 1 ✓ |
| tinklaMCUtype | 1 (MCU1) | 1 ✓ |
| tinklaNeighbor | IC | IC ✓ |
| gtw_dashw | **0** | ? |
| tinklaVersion | 1.49 | - |
| tinklaOverrideSafetyFM | 1 | - |

### Konstanten er IKKE hardkodet

`strings | grep 1001030b` → NOT FOUND. Konstanten genereres dynamisk fra
parametre (sannsynligvis `gtw_dashw` + `dasHw` CLI-arg + car config).

## Arbeidshypotese

`DAS_fakeDasReceived` er `false` i Buddys interne state etter bil-bytte.
Buddy sender sin egen fallback-0x239 (range=1, ingen kurver) inntil den
anerkjenner fakeDAS fra openpilot.

Trigger-kondisjon for å sette `DAS_fakeDasReceived=true` er ukjent — mulig
avhengig av `gtw_dashw`-verdi, `GTW_carConfig*` CAN-frames, eller specifikt
openpilot-port.

Merk: T5-inject sendte til 127.0.0.1:20101 (loopback). tinklaBuddy lytter
muligens kun på eth0-IP. Hvis det er tilfelle betyr T5 at Buddy sender
konstanten UAVHENGIG av port-20101-input — en dedikert IC-generator-tråd.

## Neste steg

1. **Sjekk gtw_dashw**: Hva bør verdien være for preAP Model S? Mulig feil
   etter bil-bytte.
2. **Inject til eth0-IP** (ikke loopback): Test om fakeDAS-trigger kjøres via
   annen adresse
3. **strings -analyse for `gtw_dashw`**: Finn koden som bruker `gtw_dashw=0`
   for å generere IC-framen
4. **Restart tinklaBuddy**: Reset runtime-state — kan resette
   `DAS_fakeDasReceived`-flagget

## Verktøy bygget (i /tmp, ephemere — se scripts/buddy_sprint/)

- `buddy_ssh.py`: pexpect SSH-wrapper (pi/pi @ 10.5.5.1), sender kommando som
  SSH-arg, streamer til EOF
- `buddy_live_capture.py`: AF_PACKET sniffer eth0+eth1, DAS-suite tracking,
  0x239 time-series. Bruker IKKE tcpdump/base64 (ikke tilgjengelig på Buddy)
- `t5_inject_afpacket.py`: inject 0x239 + AF_PACKET capture eth1 (ny versjon)

C3 Python env for cereal: `/usr/local/venv/bin/python` med
`PYTHONPATH=/data/openpilot` fra `/data/openpilot`.
