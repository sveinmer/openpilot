# NAP Handover 2026-07-10 — LIVE CAN+ethernet: GTW eier vision-sloten, NAP-0x239 broes ikke

Full live-økt med BÅDE C3 (10.5.5.125) og Buddy (10.5.5.1) på Tinkla-nett, bilen
onroad. Bygger på og PRESISERER de tidligere 07-04-handoverne. Drevet av Sveins
prinsipp: «bilen endret seg ikke → se comma-siden». Ærlig om hva som er bevist vs
usikkert.

## 1. Live-bevist kjede (fork-uavhengig, sikkert)

1. **NAP openpilot sender 0x239 range=50 på CAN bus 0 — frisk lane-data.**
   Bekreftet på engasjert rute (00000171: latActive=16036, longActive=9384,
   uniq=383 payloads range=50) OG uengasjert (00000173). Kun src=128 (bus 0 TX).
   Ingen fremmed range=1 på CAN. → openpilot/panda-encoding er ikke problemet.
2. **Tesla-ethernet-topologi (fra Buddy `/etc/hosts`):**
   `.100=cid, .101=ic, .102=gw (Tesla Gateway/BIL), .103=ape (Buddy)`.
   Buddy emulerer AutoPilot-ECU (ape). Tidligere «.102=Tinkla-gw» var FEIL.
3. **gw (Tesla GTW) broer status-frames men EIER vision-sloten:**
   Samtidig CAN-vs-ethernet-diff (gw @ .102):
   | Frame | CAN (openpilot) | gw→ethernet | 
   |---|---|---|
   | 0x659, 0x399, 0x389 (status) | openpilots verdier | **broet** (kun checksum rewritten) |
   | **0x239 (lanes)** | range=50 | **range=1 idle** |
   | **0x309 (lead)** | varierer uniq=18 | **0x00…00 null** |
   → GTW broer status fra bus 0, men genererer sin egen idle for de to
   APE-vision-framene (0x239 lanes, 0x309 lead). Bilen gjør akkurat det den
   alltid gjør — forventer vision fra APE, ikke fra CAN.
4. **Buddy (ape) forwarder gw's idle 0x239 byte-identisk** (`1001030b00011212`
   på både .102:20101 og .103:20201). Buddy injiserer IKKE openpilots lanes.
5. **GTW_status 0x348 (IC-trigger) ankommer** (80 frames/8s live). Panda
   safety_param=15 (IC-flag satt, red panda type 0x06, live).
6. **openpilots vision-frames når ALDRI Buddy** på noen ethernet-port
   (20101/20201/31415/31515 sjekket — kun idle).

## 2. Tinkla-vs-NAP: den sannsynlige mekanismen (delvis usikkert)

Sammenligning med Tinkla-æra-rlog (2026-04-30, dato-navn = Tinkla-fork, kurver
VIRKET) avslørte:
- **Tinkla-panda sendte HELE IC-suiten (0x239, 0x309, 0x329…0x3e9 + 0x488) på
  en egen kanal `src=192` (= bus 64 + returned-offset 0x80).** Dette er en
  APE-emulerings-kanal — frames injisert som om de kom fra AutoPilot-ECU.
- **NAP-panda produserer ALDRI src=192.** src-verdier i NAP-rute = {0,1,2,128,
  129,130} (standard bus 0/1/2 RX+TX). NAP-panda (tesla_preap.h) sender IC-emit
  på **bus 0** (`preap_ic_send_messages` → `can_send(bus 0)`), og hud_module
  sender vision på chassis bus 0 (teslacan.py:7 «sendt på chassis bus 0»).

**Hypotese (forklarer Tinkla-virket vs NAP-stuck):** GTW broer bus 0 for
status-frames, men eier 0x239/0x309-vision-sloten og broer dem IKKE fra bus 0.
Tinkla omgikk dette ved å injisere vision på en APE-kanal (bus 64/src=192) som
GTW/IC godtok som APE-output. NAP sender vision på bus 0 → GTW ignorerer det →
IC får GTW's idle. **Kurvene har aldri kommet via bus-0-broing; de kom via
APE-kanal-injeksjon som NAP mangler.**

## 3. ⚠️ Ærlig usikkerhet
- Alle NAP-ruter på disk er 2026-07-08/09 (alle stuck). **NAP-06-20-ruta (som
  memory sier virket) er slettet** — jeg kunne IKKE sammenligne NAP-virket vs
  NAP-stuck direkte. src=192-analysen krysser fork-grensen (Tinkla-panda vs
  NAP-panda src-koding), så «src=192 forsvant» er IKKE en ren NAP-regresjon —
  det er en Tinkla-vs-NAP arkitekturforskjell.
- Åpent: virket NAP 06-20 fordi panda DA kjørte Tinkla-firmware (bus 64), og
  bil-byttet re-flashet NAP-panda (bus 0)? Eller har NAP en egen APE-kanal-sti
  som ble deaktivert? Uavklart uten NAP-06-20-data eller Tinkla-panda-firmware.

## 4. Neste steg (kodeanalyse, ingen hardware)
1. **Finn hvordan Tinkla-panda injiserte IC på bus 64.** Skaff Tinkla safety
   (safety_tesla.h, teslaPreAp_send_IC_messages ~L805 refereres i tesla_preap.h
   kommentarer). Se om den sender på en APE/bus-64-kanal.
2. **Avgjør om NAP bør injisere vision (0x239/0x309) på APE-bussen** i stedet
   for/i tillegg til bus 0, slik at GTW broer dem som APE-output. Panda
   `preap_ic_send_messages` sender bus 0 — test bus-2/APE-variant.
3. **ALT: Buddy-injeksjon.** Buddy (ape) kunne erstatte gw's idle 0x239 på vei
   til IC med openpilots lane-data. Men Buddy leser kun ethernet (der vision er
   idle), så den trenger en kilde — samme problem.
4. Verifiser panda-firmware-historikk: ble panda re-flashet ved bil-byttet
   (Tinkla→NAP firmware)? `Panda().get_version()` / git-historikk for
   tesla_preap.h IC-emit-bus.

## 5. Eliminert denne + tidligere økter
Buddy (forwarder bare), fakeDas-latch (satt=1), Buddy dashw-emulering (IC=AP1
korrekt), brede openpilot-toggles (enableICIntegration/should_send/
preap_has_ic_integration alle åpne — søster-status-frames lever), panda-cache-
kode-sunnhet, openpilot 0x239-encoding (range=50 frisk på CAN).

## 6. Verktøy (denne økten)
`scripts/nap_ic_curve_analysis/live_2026_07_10/`:
- `c3_0x239_sources.py`, `c3_allsrc.py` — 0x239 per src på CAN (live)
- `c3_dassuite.py` — DAS-suite range/uniq på CAN
- `c3_buslayout.py` — CAN bus-layout (src→arb)
- `c3_trigger.py` — GTW_status 0x348-trigger + src=192/128 IC-frames (live)
- `rlog_raw2_0x239.py` — 0x239 per src offline (håndterer rlog + rlog.zst;
  dato-navn-ruter: les rått, ikke via LogReader/SegmentRange)
- `rlog_srcmap.py`, `rlog_trigger.py` — src-mapping + trigger offline

C3-tilgang: `ssh comma@10.5.5.125` (nøkkel-auth, ingen passord). Env:
`PYTHONPATH=/data/openpilot /usr/local/venv/bin/python` fra `/data/openpilot`.
Buddy: `python3 /tmp/buddy_ssh.py` (pi/pi), AF_PACKET (ingen tcpdump).
Tinkla-æra-rlogs (før switch, ukomprimert `rlog`): `/data/media/0/realdata/2026-04-*`.
