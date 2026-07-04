# NAP 0x239 — syntese via Sveins prinsipp «bilen endret seg ikke» (2026-07-04 sen kveld)

Svein utfordret sporet: fokuset manglet på at dette **fungerte før bil-byttet**,
og det er usannsynlig at *bilen* plutselig oppfører seg annerledes. Det eneste
som endret seg gjennom Tesla→Ampera→Tesla er **comma/openpilot/panda-config**.
Denne linsen ga den skarpeste innsikten i saken. Ærlig status under.

## 1. Problemet er 0x239-SPESIFIKT, ikke en bred IC-toggle
Nøkkelobservasjon (fra Buddy-capturene): søster-DAS-framene **0x399, 0x389,
0x309 varierer på ethernet** samtidig som **0x239 er idle (range=1)**. Alle fire:
- ligger bak `CS.enableICIntegration` i hud_module,
- er IC-gated i panda (`preap_has_ic_integration`).

At søstrene lever ⇒ **alle disse comma-side-gatene er beviselig ÅPNE:**
- `enableICIntegration = True` (ellers dør 0x399/0x389 også — de er under samme if)
- `preap_has_ic_integration = True` (ellers blokkerer panda IC-gaten alle 9 addr)
- `should_send = True` (hud_module L284: alltid True for `carFingerprint ==
  TESLA_MODEL_S_PREAP`, uavhengig av enabled)

Så 0x239 er IKKE offer for en toggle som slo av. Noe rammer **kun 0x239**.

## 2. Selvmotsigelsen (kan ikke løses fra kode alene)
Med alle gates åpne SENDER comma-siden 0x239 med `laneRange=50` (hardkodet,
hud_module L328; panda re-emitter openpilots bytes eller ingenting — aldri
range=1). Likevel viser ethernet range=1.

→ comma sender range=50, ethernet viser range=1. **Ekte selvmotsigelse.**
Den kan bare brytes ved å måle bussen, ikke lese kode.

## 3. Den avgjørende, ikke-kjøre-avhengige testen: TELL 0x239-KILDER på CAN
Sveins prinsipp peker på den enkle testen ingen har kjørt: **hvor mange
0x239-sendere (src) er på CAN, og hva er deres range?** (memory sa «src=128,
range=50» — men aldri sjekket om det finnes en ANNEN src med range=1.)

Verktøy (offline på fersk rlog — INGEN kjøring):
`scripts/nap_ic_curve_analysis/c3_can_0x239.py --rlog <rute>/rlog`

**Utfall X — kun src=128, range=50 (én kilde):**
  0x239 er frisk og alene på CAN. Overstyringen til range=1 skjer NEDSTRØMS
  (gw/bil-bro fyller IC-sloten med noe annet). Da MÅ vi akseptere at bil/gw
  behandler 0x239 spesielt — men mål ethernet samtidig for å låse det.

**Utfall Y — en EKSTRA src med range=1 (to kilder):**
  Bilens egen native idle-DAS_lanes ligger på bussen ved siden av vår. DEN er
  synderen, ikke openpilot. Neste: diff mot en FØR-switch rlog — dukket
  range=1-kilden opp etter bil-byttet? (Bilens DAS-subsystem kan ha endret
  send-tilstand ved coding/retrofit-touch under bil-byttet — men det er da en
  bil-config-endring vi kan påvise, ikke «bilen oppfører seg tilfeldig».)

**Utfall Z — ingen range=50 i det hele tatt:**
  Tross at §1 sier gates er åpne, sender ikke openpilot 0x239. Da er §1-analysen
  ufullstendig (en gate lukket i kjørende stack vi ikke fant statisk). Finn den.

## 4. Hvorfor dette respekterer «bilen endret seg ikke»
- Utfall X/Z: comma-side eller bro-mekanisme — bilen speiler bare fravær/nærvær.
- Utfall Y: en påvisbar bil-config-delta fra selve bil-byttet (ikke tilfeldig
  oppførsel) — testbar ved rlog-diff før/etter.
I alle tre er neste steg en KONKRET måling, ikke mer kode-spekulasjon.

## 5. Ærlig avgrensning
Jeg kan ikke fra koden alene forklare hvorfor kun 0x239 rammes når alle gatene
er åpne. Det krever den ene målingen i §3. Alt annet (Buddy, latch, dashw, brede
toggles, panda-cache-sunnhet) er eliminert. Kjøres `c3_can_0x239.py --rlog` på
nyeste stuck-rute + en før-switch-rute, faller saken sannsynligvis på plass.

## 6. Sveins meta-poeng (notert)
Sporet gikk for dypt i teknisk RE før noen stilte det enkle spørsmålet «hva
endret seg, og er det sannsynlig at bilen gjorde det?». Den disiplinen —
kilde-telling og før/etter-diff framfor mekanisme-graving — burde vært brukt
tidligere. Verktøyet i §3 er bygget for nettopp det.
