# NAP Fix-plan — 0x239 IC-kurver (utkast 2026-07-10)

**Status:** Rotårsak IKKE 100% bekreftet. Denne planen er diagnose-først:
avklar rotårsak med kode-uavhengige tester, DERETTER fiks per utfall. Ikke
implementer en fiks før Fase 0 peker entydig. Svein presset (berettiget) på at
«koden var bit-lik» — hvis sant, er fiksen RUNTIME/STATE, ikke kode.

## Bekreftet tilstand (solid, live-målt 2026-07-10)
- NAP openpilot sender **0x239 range=50 frisk på CAN bus 0** (engasjert + parkert).
- Tesla GTW (.102=gw) **eier vision-sloten**: sender idle 0x239 (range=1) + null
  0x309 til ethernet; broer status-frames (0x659/0x399/0x389) korrekt.
- Buddy (.103=ape) **forwarder** GTW's idle 0x239 byte-identisk.
- GTW_status 0x348 IC-trigger ankommer. Panda red (0x06), safety_param=15.
- IC-frames er display-only (risk-tier 3, ingen kjøre-/aktuator-effekt) →
  lav-risiko å endre.

## Rotårsak-kandidater (rangert)
- **K1 — Panda/Buddy IC-injeksjon runtime-død** (mest sannsynlig gitt «bit-lik kode»)
- **K2 — Vision-injeksjon når aldri IC-slot** (arkitektur/kanal; kode hvis endret)
- **K3 — Param/fingerprint/state endret ved bil-bytte**
- **K4 — C3-kode avviker fra 06-20** (motbeviser «bit-lik» — må sjekkes direkte)

---

## FASE 0 — Avklar rotårsak (ingen kode-endring, mest kode-uavhengig først)

**0.1 Verifiser «bit-lik kode» DIREKTE på C3 (ikke anta):**
- `ssh comma@192.168.0.65` → `cd /data/openpilot && git log --oneline -5 && git status --short`
  og submodule `opendbc_repo` samme. Er HEAD/working-tree = det som kjørte 06-20?
  (Tidligere handover: opendbc-tree var «dirty med vilje» pga sweep-patch —
  sjekk om patchen er reverted; original sha256 i 07-02-handover.)
- Panda-firmware: `Panda().get_version()` / git-versjon. Ble panda re-flashet
  ved bil-byttet? Sammenlign mot 06-20 hvis mulig.
- **Utfall:** kode/firmware avviker → K4 (checkout/flash korrekt). Bit-lik → K1/K3.

**0.2 Kjører panda IC-emitteren? (counter-rotasjon — kode-uavhengig):**
- Les nyeste rlog offline: fordeling av `byte7>>4` (DAS_lanesCounter) på 0x239.
  Verktøy: `scripts/nap_ic_curve_analysis/live_2026_07_10/` (utvid til counter).
- Panda IC-emit roterer counter 0..15; openpilot-direkte = konstant 1.
- **Utfall:** kun {1} → panda IC-emit DØD (K1). Roterer 0..15 → IC-emit lever
  (da er problemet nedstrøms: injeksjonskanal/Buddy → K2).

**0.3 IC-params i KJØRENDE prosess (ikke bare disk):**
- `NAPTinklaICIntegration`, `NAPForcePreAP`, `CarParamsPersistent` fingerprint.
- Bekreft `enableICIntegration=True` i kjørende carstate (proxy: sender openpilot
  status-frames 0x399/0x659? — ja, bevist, så True). Panda `preap_has_ic_integration`
  = safety_param bit 3 (=15 → satt).
- **Utfall:** param feil i prosess tross disk-verdi → K3 (reboot-rekkefølge).

**0.4 Hvordan nådde 06-20-vision IC? (avgjør K2):**
- Skaff Tinkla safety (`safety_tesla.h`, `teslaPreAp_send_IC_messages` ~L805 —
  refereres i vår tesla_preap.h). Hvilken bus/kanal injiserte Tinkla 0x239 på?
- Sjekk om NAP-panda `preap_ic_send_messages` (bus 0) er ment å nå IC-slot, eller
  om Buddy (ape) skal injisere. Buddy forwarder nå — SKAL den bygge/erstatte?
  (process_DI_state bygger 0x239 fra state, men lane-geometri-kilden er uklar —
  åpen tråd fra 07-10-økten.)

---

## FASE 1 — Fiks per bekreftet rotårsak

### Hvis K4 (kode/firmware avviker)
- Checkout/reflash til den versjonen som kjørte 06-20. Laveste risiko, ingen
  ny kode. Verifiser med Fase 2.

### Hvis K1 (panda IC-emit runtime-død, kode bit-lik)
- Finn hvorfor emit ikke produserer tross safety_param=15:
  - `preap_ic_emit_message` returnerer hvis `!cache.valid`. Cachen fylles av
    `preap_ic_capture_tx` (gated `tx && preap_has_ic_integration`). Sjekk om
    openpilots 0x239 faktisk treffer capture (tx_hook-sti).
  - Boot-rekkefølge: settes safety-param FØR første IC-TX? Hvis param settes
    sent, kan tidlig state være feil til reboot.
- **Fiks:** kald reboot av C3+panda med NAPTinklaICIntegration bekreftet satt
  FØR manager forker (lav-risiko, ingen kode). Hvis capture-gate er buggen:
  minimal panda-patch — men KUN hvis 0.1 viser koden faktisk endret.

### Hvis K2 (vision når aldri IC-slot — kanal/arkitektur)
- GTW eier 0x239/0x309-sloten; bus-0-injeksjon broes ikke. Alternativer:
  - **(a) Buddy-injeksjon:** få Buddy (ape) til å erstatte GTW's idle 0x239 på
    eth1 med openpilots lane-data. Krever at openpilots lane-data når Buddy
    (i dag gjør den ikke — gw broer ikke vision). Undersøk om Tinkla matet Buddy
    via en egen frame/kanal.
  - **(b) Panda APE-kanal:** injiser 0x239/0x309 slik at GTW ser dem som
    APE-output (Tinkla brukte src=192/bus64). KODE-endring i panda IC-emit-bus.
    KUN hvis 0.1 viser at NAP-koden faktisk skal gjøre dette og regredierte.
- **Advarsel:** (b) er en reell kode-endring på et system som «virket med bit-lik
  kode» — motsier bit-lik-premisset. Ikke gjør (b) før K4/K1/K3 er utelukket.

### Hvis K3 (param/state)
- Sett korrekt param, kald reboot, re-fingerprint hvis nødvendig. Verifiser
  CarParamsPersistent = TESLA_MODEL_S_PREAP + IC-params. Lav-risiko.

---

## FASE 2 — Verifisering (samme for enhver fiks)
1. **Counter-rotasjon** på 0x239 tilbake (hvis K1) — rlog offline.
2. **Ethernet-capture på Buddy:** 0x239 fra gw/ape = range=50 varierende (ikke
   idle). Verktøy: `scripts/buddy_sprint/live_2026_07_04/onroad_0x239_source.py`.
3. **Foto/video av IC** i kjent sving — kurver animerer. Objektivt før/etter.
4. Kjør en rute, bekreft stabilt over tid.

## Sikkerhet / risiko
- IC-frames = display-only, risk-tier 3 (tesla_preap.h). Ingen aktuator-/engage-
  effekt. Reboot og param-endringer er lav-risiko.
- Kode-endring i panda (K2b) berører safety-firmware — krever full kausalkjede-
  gjennomgang + test før flash. Siste utvei.
- Følg `feedback_buddy_temp_only`: ingen permanente Buddy-endringer uten bevis.

## Anbefalt rekkefølge
0.1 → 0.2 → 0.3 (raske, kode-uavhengige, offline/rlog) → 0.4 (kodeanalyse) →
velg fiks. Start ALLTID med laveste-risiko utfall (K4 checkout / K3 reboot)
før kode-endring (K2b).
