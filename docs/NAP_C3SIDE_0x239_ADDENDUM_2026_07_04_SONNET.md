# NAP C3-side 0x239 — addendum 2026-07-04 (Sonnet, forts. fra Fables C3-side-funn)

Bygger på `NAP_C3SIDE_0x239_FINDINGS_2026_07_04_FABLE.md`. Ren kodeanalyse +
Buddy-binær-RE (ingen live — bilen er av, Svein borte fra bilen). Bekrefter
Fables «range=1 er fremmed», legger til én mekanistisk innsikt og skjerper den
decisive testen slik at den skiller de to gjenstående hypotesene entydig.

## 1. Uavhengig bekreftelse: range=1 er umulig fra openpilot
- `create_lane_message` (teslacan.py:116) sender `DAS_virtualLaneViewRange`
  fra argumentet `laneRange`. Eneste kaller (hud_module.py:328) gir **50 hardkodet**.
- Full dekoding av de tre historiske idle-framene bekrefter samme signatur:
  `xx 01 03 0b …` → lExist=rExist=0, **range=1**, C0_raw=3, C1_raw=11, counter=1.
  Byte 4–6 (status) varierer litt; kjernen er en stabil Tesla-idle-DAS_lanes.
- → Framen er ikke fra vår stack. Enig med Fable.

## 2. NY mekanistisk innsikt: 0x659 og 0x239 har ULIK send-gate i openpilot
Dette forklarer HVORFOR nettopp 0x659 varierer på ethernet mens 0x239 er idle —
uten å måtte anta at GTW «behandler dem ulikt»:

| Frame | Send-betingelse (hud_module.py) | På chassis_bus? |
|---|---|---|
| **0x659** DAS_fake | **sendes ALLTID** (L367: «independent of enableICIntegration») | ja (bus 0) |
| **0x239** DAS_lanes | **kun hvis `CS.enableICIntegration`** (L322/326) | ja (bus 0) |

`enableICIntegration` leses ÉN gang i `carstate.__init__` fra param
`NAPTinklaICIntegration` (carstate.py:82) — **ikke live**. Default False.

**Hvis `enableICIntegration` er False i den KJØRENDE prosessen** (f.eks. param satt
etter at manager forket/pre-importerte carstate — samme timing-klasse som
`feedback_manager_preimport` i 07-02-handoveren), da:
- 0x659 → sendes → GTW broer → **ethernet varierer** ✅ (matcher observasjon)
- 0x239 → sendes ALDRI → GTW har ingenting → **idle range=1** ✅ (matcher observasjon)

Dette reproduserer HELE symptombildet med én årsak, og ville vært en ren
openpilot/param/reboot-fix — ikke et Tesla-GTW-mysterium.

## 3. MEN: 07-02-data peker mot at openpilot FAKTISK sender 0x239
07-02-handoveren (§3.2/§4b) rapporterte 0x239 på CAN med lane-data (range=50
implisitt) på stuck-ruter 00000131/136, og «sendcan 0x239 == can-ekko» (src=128)
på 0000013d. Det antyder `enableICIntegration=True` og at openpilot SENDER 0x239.
Hvis det stemmer post-bil-bytte, er §2-hypotesen falsifisert og Fables GTW-spor
(openpilot sender, GTW broer ikke) står.

**Advarsel (samme som Fables):** CAN-siden (range=50) og ethernet-siden (range=1)
er ALDRI målt SAMTIDIG i samme kjøring. 07-02 målte CAN; 07-04 målte ethernet.
Uten samtidighet kan vi ikke utelukke at prosess-state (enableICIntegration)
skiftet mellom øktene.

## 4. DECISIVE TEST — skjerpet, skiller §2 vs Fables GTW-spor entydig
Krever bil PÅ. Kjør de to SAMTIDIG:

1. **C3 CAN-side:** `scripts/nap_ic_curve_analysis/c3_can_0x239.py` (ny). Leser
   `sendcan` + `can` for 0x239, dekoder range, rapporterer uniq + ranges.
2. **Buddy ethernet-side:** `scripts/buddy_sprint/live_2026_07_04/onroad_0x239_source.py`.

**Utfall A** — CAN: range=50 varierer  +  ethernet: range=1 konstant
  → openpilot sender, `gw`/GTW broer ikke openpilots 0x239 → **GTW/gw-sak**
    (Fables spor). Neste: hvorfor slutter GTW å forwarde/bygge openpilots 0x239
    etter bil-bytte mens 0x659 fortsatt broes.

**Utfall B** — CAN: 0x239 fraværende / range≠50
  → openpilot sender ikke 0x239 → `enableICIntegration` False i prosess →
    **openpilot/param/reboot-fix**. Verifiser param live og reboot-timing.

**Ekstra billig sjekk (bil på, uansett utfall):** bekreft `enableICIntegration`
i kjørende carstate. Hvis eksponert i et memory/log, les direkte; ellers er
utfall B i c3_can_0x239.py en proxy (ingen 0x239 på sendcan = flagget er False).

## 5. Utelukket denne økten (Buddy-binær-RE, v1.49)
- **Buddys dashw-emulering er korrekt.** `process_GTW_carConfig3` (@0x406780)
  overskriver dashw-feltet (byte6 bits 4–5) i carConfig mot IC med Buddys
  `GTW_dasHw` (default 1=AP1, fra `-dasHw`-arg; Sveins boks kjører uten arg →
  AP1). Så IC får dashw=AP1 og er i AP-modus — mottakssiden er klar for lanes.
  Dashw-emulering er IKKE årsaken.
- Bekrefter dermed at problemet er innholdet i 0x239-sloten (idle), ikke at IC
  avviser gyldige lanes.

## 6. Oppsummert hypotese-status
- ❌ Buddy MITM-erstatter (07-04 morgen) — motbevist
- ❌ fakeDas-latch=0 (Fable v1.44) — motbevist (latch=1 live)
- ❌ Buddy dashw-feilemulering — utelukket (IC får AP1)
- ⏳ **Fables GTW-spor** (openpilot sender, GTW broer ikke) — ledende hvis Utfall A
- ⏳ **enableICIntegration=False i prosess** (denne økten) — hvis Utfall B
- Én samtidig CAN+ethernet-måling avgjør. Verktøy klart for begge sider.
