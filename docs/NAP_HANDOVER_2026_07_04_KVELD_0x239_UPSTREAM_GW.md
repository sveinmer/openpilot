# NAP Handover 2026-07-04 (kveld) — IC-curves: BUDDY FRIKJENT, kilden er «gw» (192.168.90.102) oppstrøms

> **Dette dokumentet SUPERSEDER root-cause-retningen i:**
> - `docs/NAP_BUDDY_0x239_FINDINGS_2026_07_04.md` (Sonnet, live-sesjon)
> - `docs/NAP_BUDDY_0x239_ROOTCAUSE_MERGED_2026_07_04.md` (Fable, binær-RE)
>
> Begge konkluderte «Buddy MITM-erstatter 0x239 / fiks fakeDas-latchen».
> **Det er nå MOTBEVIST med live binær- + prosessminne- + per-port-kilde-bevis.**
> Panda-elimineringen fra 07-02 og oppstrøms-modell-friskheten står fortsatt.

**Regel:** ingen påstand uten evidens ved siden av. Alt under er live-målt
2026-07-04 kveld (Buddy @ 10.5.5.1, bil kjørende mens Svein kjørte på min
kommando). Verktøy + hentet v1.49-binær er committet (se §6).

---

## 1. TL;DR

- **Buddy er frikjent.** 0x239 DAS_lanes ankommer Buddys chassis-inngang
  (eth0, UDP 20101) **allerede som konstant `1001030b80011212`** (range=1,
  ingen kurver) — også ONROAD. Buddy videresender bare det den mottar.
- **Latchen er IKKE problemet.** `DAS_fakeDasReceived` lest LIVE fra Buddys
  `/proc/PID/mem` = **1 (satt)**. 0x659 varierer korrekt (404 unike) og
  ankommer 20101. Buddy tar altså den EKTE-grenen, ikke fallback.
- **Kilden til konstant-0x239 er `192.168.90.102` (hostname `gw`,
  MAC `00:00:a7:01:02:03`)** på chassis-siden — samme enhet som sender korrekt
  varierende 0x659. Dvs. **oppstrøms-senderen sender 0x239 som en konstant
  idle-frame mens resten av DAS-suiten varierer.**
- **Sannsynlig rotårsak:** panda IC-emitter-cache — `preap_ic_capture_tx()`
  fanger trolig ikke openpilots 0x239 inn i cachen, så panda re-emitterer en
  stale idle-default på EtherCAN/gateway-strømmen. Alt annet (0x659 osv.)
  fanges og varierer. **Jakten flytter til C3-siden (10.5.5.125).**

---

## 2. Hva som ble MOTBEVIST (og hvorfor de tidligere sporene bommet)

### 2.1 «Buddy MITM-erstatter 0x239» — FEIL
Live per-port-capture på eth0 (Buddys FYSISKE chassis-inngang, før Buddy rører
noe) viser at 0x239 allerede er konstant `1001030b80011212` når den kommer inn.
Tidligere capturer så konstanten på eth1 (utgang) og antok Buddy genererte den —
men den er identisk på inngangen. Buddy er en ren videresender for 0x239.

### 2.2 «fakeDas-latchen er 0 → Buddy sender fallback» — FEIL
Fable (v1.44-RE) og Sonnet antok latch=0. Jeg leste den LIVE:
`DAS_fakeDasReceived` = **1**. Se §3.2.

### 2.3 «En bit-test i 0x659 gater latchen; fiks openpilot-0x659» — FEIL RETNING
v1.49-disassembly av `process_fake_das` viser at latchen (`str w8,[x0,#0x11c]`
@0x406e44) settes **ubetinget** når funksjonen kalles. Bit-testen `tbz w1,#6`
@0x406de4 er bare en frame-format-gren — BEGGE grener (0x406de8 og 0x406f00)
konvergerer på latch-blokka @0x406df0→0x406e08. Ingen 0x659-bit avgjør latchen.
Og `etherCan_regular_up` @0x40801c kaller `process_fake_das` ubetinget for enhver
0x659 (arb_hi=6, arb_lo=0x59) på port 20101. => Enhver 0x659 setter latchen
permanent til reboot. En openpilot-0x659-fiks ville ikke endre noe.

---

## 3. Bevis (reproduserbart — verktøy i §6)

### 3.1 Onroad per-port capture (Buddy eth0 = chassis-inn, mens Svein kjørte)
`scripts/buddy_sprint/live_2026_07_04/onroad_0x239_source.py`:
```
eth0 arb=0x239 dport=20101 count=550  uniq=1    first=1001030b80011212
eth0 arb=0x659 dport=20101 count=550  uniq=404  first=02002a410f327248
eth1 arb=0x239 dport=20101 count=550  uniq=1    first=1001030b80011212
```
→ 0x239 konstant (uniq=1) selv onroad; 0x659 varierer (uniq=404). Begge på
inngangs-porten 20101.

### 3.2 Live prosessminne på Buddy (`read_buddy_state.py` via /proc/PID/mem)
Binæren er **ET_EXEC** (fast adresse) → state-globals lesbare direkte.
State-base 0x4d5af0:
```
state[0x10]  (DI emit-gate)        = 1      # process_DI_state emitterer
state[0x11c] DAS_fakeDasReceived   = 1      # <== LATCH SATT
state[0x3c]  (should_forward)      = 1
```

### 3.3 Kilde-identifikasjon (`identify_source.py` — src MAC/IP på eth0)
```
arb=0x239:  src 00:00:a7:01:02:03 (192.168.90.102:49153) -> 192.168.90.255:20101
            src 7a:a7:2a:05:b0:67 (192.168.90.103:61234) -> 192.168.90.255:20201  # = Buddys egen re-emit
arb=0x659:  src 00:00:a7:01:02:03 (192.168.90.102:49155) -> 192.168.90.255:20101
```
Buddy `/etc/hosts`/getent: **`192.168.90.102 = gw`**. MAC på eth0/br0 (PERM).
Tesla-ethernet-nett: .100=GTW(02:35:..:cd), .101=IC(02:35:..:1c, Buddy eth1),
.102=**gw** (kilden), .103=Buddy br0.

→ Samme enhet `gw` sender BÅDE konstant 0x239 OG varierende 0x659. Feilen er
frame-spesifikk for 0x239 i `gw`-senderen.

---

## 4. Binær-arkitektur bekreftet på v1.49 (Sveins faktiske boks)

Committet binær: `scripts/buddy_sprint/firmware_re/tinklaBuddy.v149` (hentet med
`buddy_scp.py`, aarch64 ELF, ustrippet m/ debug_info). Reverser med
`firmware_re/{disas,xref2}.py` (venv: `capstone pyelftools`).

Nøkkel-offsets v1.49 (avvik fra Fables v1.44 i parentes):
- `DAS_fakeDasReceived` @ **0x4d5c0c** (v1.44: 0x4d3c0c) — state[0x11c]
- `process_fake_das` @ 0x406da0 — latch `str w8,[x0,#0x11c]` @0x406e44 (ubetinget)
- `process_DI_state` @ 0x406a88 — gate: state[0x10]==1 for emit; ved 0x406b24
  `cbz DAS_fakeDasReceived → fallback` (idle-frame). Kun `process_fake_das`
  skriver latchen (xref bekreftet).
- Dispatch-kjede: `process_packet`(IP) → `process_udp_packet`(port) →
  `etherCan_regular_up`(20101: 0x659→process_fake_das, GTW_carConfig) /
  `etherCan_h_up`(31415: DI_state→process_DI_state).

Konklusjon: Buddy-logikken er sunn og gjør akkurat det den skal. Latchen satt,
gate åpen, videresender kilden. Problemet er utenfor Buddy.

---

## 5. NESTE STEG — C3-siden (10.5.5.125), for kollega på annen laptop

Målet: finn hvorfor `gw`/192.168.90.102 sender konstant 0x239 mens resten varierer.

1. **Identifiser `gw`/192.168.90.102 fysisk.** Er det C3s kablede ethernet mot
   Tesla-nettet, eller pandas ethernet? Sjekk `ip -br addr` på C3 og se om den
   har 192.168.90.102 / MAC 00:00:a7:01:02:03. (C3 WiFi = 10.5.5.125,
   MAC 00:0a:f5:7f:ee:2e — så .102 er et ANNET, kablet grensesnitt.)
2. **Sammenlign 0x239 CAN vs EtherCAN live.** Fra 07-02: `can`-service TX-echo
   (src=128) = `6032647d…` VARIERER. Men EtherCAN til Buddy = `1001030b…`
   KONSTANT. Bekreft at dette er to ulike strømmer:
   - CAN 0x239 (openpilots direkte sendcan-TX) — varierer ✓
   - EtherCAN/IC-emit 0x239 (det `gw` sender) — konstant ✗
   C3-venv: `/usr/local/venv/bin/python`, `PYTHONPATH=/data/openpilot`, fra
   `/data/openpilot` (per tidligere handover §5).
3. **Panda IC-emitter-cache — hovedmistanke.** Les
   `opendbc_repo/opendbc/safety/modes/tesla_preap.h`:
   - `preap_ic_capture_tx()` (~L412): fanger den openpilots 0x239 inn i cache-
     sloten? Sjekk om 0x239 er i capture-listen/at valid-flagget settes.
   - `preap_ic_emit_message()` (~L462): emitterer 0x239 fra cache — hvis cachen
     aldri fylles for 0x239, sendes en stale/default (= `1001030b…`?).
   - Sammenlign 0x239-håndteringen mot 0x659 (som VIRKER) — hva er forskjellen?
   Dekod `1001030b80011212`: range=1, lExist=rExist=0 → en tom/idle DAS_lanes.
   Ser ut som en uinitialisert/default cache-frame.
4. **Hvem pakker CAN→EtherCAN til `gw`?** Finn prosessen på C3/panda som
   genererer EtherCAN-UDP mot 192.168.90.255:20101. Der ligger 0x239-buggen.

**Hurtigtest hvis usikker:** fang samtidig `can`-service (0x239 payloads) og
EtherCAN-utgang på C3 mens onroad. Hvis CAN varierer men EtherCAN er konstant →
bekreftet at IC-emit/EtherCAN-laget er synderen, ikke openpilots lane-encoding.

---

## 6. Verktøy committet denne økten

`scripts/buddy_sprint/live_2026_07_04/`:
- `buddy_ssh.py` — pexpect SSH-wrapper (pi@10.5.5.1 (passord: BUDDY_PASS, lokal memory)), kommando som SSH-arg.
- `buddy_scp.py` — pexpect scp-wrapper (hentet v1.49-binæren).
- `read_buddy_state.py` — leser tinklaBuddy state-globals live via /proc/PID/mem
  (DAS_fakeDasReceived m.fl.). ET_EXEC → faste adresser.
- `identify_source.py` — src MAC/IP per arb-id på eth0 (fant `gw`).
- `onroad_0x239_source.py` — per-(iface,arb,dport) capture + 0x239 tidsserie.
- `perport_capture.py` — kort per-port 0x239/0x659-snapshot.

`scripts/buddy_sprint/firmware_re/`:
- `tinklaBuddy.v149` — Sveins FAKTISKE binær (1.4 MB, ustrippet). Reverser med
  `disas.py <bin> <symbol>` / `xref2.py <bin> <global>`.

Buddy har IKKE tcpdump/base64 — alle capturer bruker AF_PACKET-Python via sudo.

---

## 7. Åpne tråder / advarsler
- `gw`/192.168.90.102 sin fysiske identitet er ikke 100% bekreftet (C3-ethernet
  vs panda) — steg 5.1 avgjør.
- Devicens klokke er bogus før NTP-sync (per 07-02) → ikke stol på mtimes på C3.
- Den konstante `1001030b80011212` er nær identisk med tidligere observert
  `1001030b00011212`/`7001030b80101611` — samme `030b`-signatur, dvs. samme
  idle-default-frame gjennom hele historikken. Dette er en STABIL default, ikke
  støy → styrker «uinitialisert cache»-hypotesen.
