# NAP Handover 2026-07-02 (kveld) — IC-curves: oppstrøms ELIMINERT med data, root-cause-kandidat = Buddy ACC-state-gate

> ## ⚠️ KORREKSJON (samme kveld, etter Sveins innsigelse) — §1-kandidaten og §4-testen er TILBAKETRUKKET
>
> Svein korrigerte: han kjørte long-aktiv med normal MAX-visning 01.07, kurvene
> fortsatt stuck. Verifisert i rlogs (min opprinnelige ruteliste hadde en
> regex-feil som mistet 15 av 19 hex-ruter; 29–30.06-rutene jeg bygde på var
> ikke representative):
>
> - `0000013d` (33 seg) og `0000013c` (34 seg): **longActive 59 %/52 %**,
>   0x659 byte1 = reelle target-hastigheter (110/70/80/41 km/h) under
>   engasjement, 0x389 = reell cruise-speed. Buss-state **identisk med
>   fungerende 06-20 i alle felt** — og kurvene var likevel stuck.
> - **ACC-state/Buddy-gate-hypotesen er DØD.** §3.3-dataene var korrekte, men
>   utvalgs-skjeve; §3.1–3.2 (oppstrøms-eliminering) står uendret.
> - Frame-kadens sjekket i tillegg: 0x239/0x659/0x309 eksakt 10 Hz begge æraer
>   (median 100 ms, maks ~106 ms, null gaps >300 ms). Tidsdomenet eliminert.
>   0x309-vision-fallback-flooden fantes også på fungerende 06-20 (ratio 1.0).
>
> **Status etter korreksjonen: ALT målbart på sendersiden er identisk mellom
> fungerende og stuck tilstand** (innhold, verdier, saturering, korrelasjon,
> kadens, meldingsmiks; TX-til-buss bekreftet via can-ekko 07-01). Gjenstående
> hypoteser gjør motsatte prediksjoner — se ny §4b.

**Superseder** hypotesedelen (§2) i `NAP_HANDOVER_2026_07_02_PANDA_BYTE_ELIMINATED.md`.
Panda-elimineringen der står. Denne økten gjennomførte handoverens "eneste
gjenstående decisive test" (§3) — **offline fra eksisterende rlogs på devicen,
uten ny kjøring** — og gikk lenger: full felt-diff av DAS-suiten mellom
fungerende og stuck æra.

**Regel:** ingen påstand uten evidens ved siden av. HYPOTESE er merket.

---

## 1. TL;DR

- **Oppstrøms er ELIMINERT med data:** modellens `position` er frisk, polyfitten
  beregnes korrekt, og det som sendes i 0x239 i dag er **statistisk identisk**
  med det som ble sendt da kurvene beviselig virket (Tinkla mai-æra OG NAP 06-20).
- **Eneste felt-forskjell i hele DAS-suiten under engasjert kjøring:**
  `0x659 byte1 (acc_speed_kph)` = **105** på fungerende 06-20-rute vs **0 i 100 %**
  av post-switch-meldingene (også under engasjement). Sekundært: `0x389 byte0`
  (DAS_status2 cruise-speed) = reell fart (70) før vs fallback-10 (raw 50) nå.
- **Årsaken til feltforskjellen:** alle post-switch-engasjementer var
  **lateral-only (JustCC)** — pedal-long var aldri aktiv (0x551-pedalkommando
  konstant 0 hele æraen). `pedal_speed_kph` fanges kun ved double-pull med
  `pedal_long_allowed` (`engagement.py:83,142`), ellers 0.
- **HYPOTESE (root-cause-kandidat):** Buddys MITM-pipeline gater lane-path-
  animasjonen på ACC-aktiv-state (samme mekanisme som 2026-05-25-funnet for
  MAX-widgeten: feltverdier i 0x659/0x2B9 styrer pipeline-trigger). Med
  acc_speed=0 fryser/degraderes path-rendringen → "rette / stuck på én sving".
- **Ampera-byttet er red herring for selve IC-en.** Det som endret seg 06-24 er
  *hvordan det kjøres*: 06-20 var 61 % engasjert med pedal-long (acc_speed=105);
  post-switch-rutene er 7–21 % engasjert, alt lateral-only.

---

## 2. Metode (reproduserbar)

Ferske **fulle rlogs ligger på devicen**: `/data/media/0/realdata/00000131*`
(29.06, 97 seg), `00000134` (29.06), `00000136` (30.06), `00000138` (30.06).
I tillegg ligger **460 preserverte Tinkla-æra-rlogs** (2026-04-30…05-08,
date-style navn = Tinkla-fork). Fungerende NAP-rute 06-20 (`00000104--c5a7306ffa`)
hentet som public qlog (desimert `sendcan` finnes der; `can` gjør ikke).

Analysescripts (kjørt på C3 med `/usr/local/venv` + PYTHONPATH per forrige
handover §5): `scripts/nap_ic_curve_analysis/` i WSL-repoet
(`ic_curve_analysis.py`, `ic_curve_analysis2.py`, `ic_curve_analysis3.py`,
`ic_curve_ab.py`, `das_suite_ab.py`, `qlog_das_decode.py`).

Fasit for veikurvatur: `livePose.angularVelocityDevice.z / vEgo` (IMU, uavhengig
av CAN-fortegn). Fortegnsvalidering: `modelV2.action.desiredCurvature` (driver
styringen, som virker) korrelerer **+0.95…+0.98** med IMU-fasit → fasit korrekt.

---

## 3. Bevis

### 3.1 Oppstrøms-kjeden er frisk (rlogs 00000131 + 00000136)

| Ledd | Måling | Verdi |
|---|---|---|
| modelV2.position ankret i bilen | y[0] | ≡ 0.0 (std 0) |
| position inneholder vei-signalet | corr(punkt-kurvatur@15 m, IMU) ved preview-lag 1.25–1.5 s | **+0.86 / +0.76** |
| modellen ser veien | corr(desiredCurvature, IMU) | **+0.95 / +0.93** |
| sendt 0x239 == polyfit(modelV2) | corr(sendt C2, rekonstruert C2) | **0.94 / 0.98** |

### 3.2 …men 0x239-innholdet var LIKE "dårlig" da det virket

Kubikk-fitten over hele horisonten (x[-1] ≈ 180–200 m) + DBC-clip ±0.0025
(≙ R=800 m) gjør at C2 saturerer på alle krappere svinger — **i begge æraer**:

| Rute | Æra / IC-status | v snitt | sat-frac C2 | corr(sendt C2, vei) @lag |
|---|---|---|---|---|
| 2026-05-03 (Tinkla) | **virket** | 74 km/t | 0.24 | ~0.37 |
| 2026-05-08 by (Tinkla) | **virket** | 26 km/t | **0.78** | ~0.58 |
| 00000131 (NAP nå) | stuck | 68 km/t | 0.42 | ~0.40 |
| 00000136 by (NAP nå) | stuck | 32 km/t | 0.72 | ~0.68 |

→ Bus-innholdet i 0x239 skiller ikke virkende fra stuck. Kurve-koden er
**ferdig eliminert** (nå med data, ikke bare byte-diff av kildekode).

### 3.3 Felt-diff av HELE DAS-suiten (das_suite_ab.py): eneste avvik = ACC-state

06-20-qloggen (12 segmenter, 49 0x659-samples) vs stuck-rutene:

| Felt | 06-20 (virket), engasjert | Stuck-ruter, engasjert |
|---|---|---|
| 0x659 byte0 (flagg+op_status) | 133 (op=5, spdCtrl=1) | **133 (identisk)** |
| 0x659 byte3 (cc_state m.m.) | 134 (cc=2) | **134 (identisk)** |
| **0x659 byte1 (acc_speed_kph)** | **105** | **0 (100 % av 1686 frames)** |
| **0x389 byte0 (cruise-speed)** | 70 (reell) | 50 (= fallback-10-hacken) |
| 0x551 pedal-cmd (bus 2) | (Tinkla-æra: aktiv) | konstant 0 hele æraen |
| 0x239 (lanes) | — | **ingen byte-diff** |

Engasjement: 06-20 = 0.61; 00000131 = 0.07–0.21; 00000136 = 0.09.
Alle post-switch-engasjementer lateral-only → `pedal_speed_kph=0`
(`engagement.py`: fanges kun ved double-pull med `pedal_long_allowed`; første
pull og brems nullstiller).

### 3.4 Symptom-match

Buddy-pipeline frossen/degradert uten ACC-state forklarer eksakt:
skilt/hastighet/MAX virker (ble eksplisitt ungated/hardkodet 2026-05-25),
lane-LINJENE tegnes, men path-kurven oppdateres ikke → "rette eller stuck på
én tilfeldig sving" (= siste state før pipelinen sluttet å oppdatere).

---

## 4. NESTE STEG — TILBAKETRUKKET (se korreksjonsblokka øverst)

~~5-minutters pedal-long-kjøretest~~ — moot: rutene 13c/13d beviser at long-
aktiv med reell acc_speed IKKE vekker kurvene.

## 4b. GJENSTÅENDE HYPOTESER — oppdatert etter Sveins vitnesbyrd

**(A) Saturerings-/render-grense: DREPT av Svein.** Tinkla tegnet levende
kurver i krappe svinger (og mai-by-loggene viser 78 % saturering der) →
saturering forklarer ikke stuck.

**(B) Mottaker-siden (Buddy/IC) er ENESTE gjenværende hypotese.**
Sveins nøkkelobservasjon: dagens rendering ser ut **nøyaktig som æraen før
DAS_lanes fantes i DBC-en** (V55/V56-hovedfeilen) — dvs. slik IC-en tegner
når den ikke får gyldig lane-data i det hele tatt. Samtidig er sendersiden
bevist ren, sist på symptomatisk long-aktiv rute 0000013d:
`sendcan 0x239 == can-ekko (3542==3542, alle src=128)`, ingen fremmed
0x239-kilde på bussen. → Buddy mottar korrekte frames men lane-path-pipelinen
forkaster/ignorerer dem; de "rette linjene" Svein ser er sannsynligvis
Buddy/IC-ens egen default-rendering, ikke våre C0–C3.

Info-notat (IKKE regresjon, samme kode 06-20): under long-aktiv sendes 0x2B9
på buss 1 (src 129 i can-ekko), ikke buss 0 — Plan C-design. Stuck skjer i
begge kjøremodi, så 0x2B9-tilstedeværelse på buss 0 diskriminerer ikke.

**Avklart med Svein + data (07-02 sen kveld):**
- Buddy ER hard-syklet (OBD2-utrekk kutter både Buddy og C3) → flyktig
  hengt-state DØD. Buddy har ingen kurve/linje-innstillinger og er urørt →
  misconfig DØD. Buddy = black box med beviselig identiske innganger.
- Bil-side buss-diff (mai vs nå): eneste delta = ~97 nye IDer på buss 1
  @14 Hz (0x300–0x383 + status) = **Tesla-radaren** — men `NAPRadarEnabled`
  mtime = 2026-05-22, dvs. radar var på FØR fungerende 06-20 → ikke
  regresjonen. Buss 0 (det Buddy hører): identiske rater på alle felles
  adresser.
- 0x2B9 byte2/3: 06-20 == nå == (128,119) (Tinkla-avviket (176,71) var
  fork-konstanter). Siste sender-løsetråd lukket.
- **Radar-kabelbrudd (Sveins info) undersøkt og lukket:** radar-trafikk
  finnes i ALLE overlevende ruter (06-28→), og 06-20-qloggen viser
  `radarState.leadOne.radar=True`-leads (58 % av samplene) → **radaren var
  i live også da kurvene virket.** Brudd+fiks ligger ikke over
  regresjonsgrensa → ikke delta. (0x309-innholds-dypdiff dermed lavprioritet;
  das_suite fant uansett ingen byte-avvik på 0x309.)

**Gjenstående testplan:**
1. **In-drive C2-sweep — DEPLOYERT PÅ DEVICE 2026-07-02 (kveld):**
   `hud_module.py` på C3 er patchet (31 linjer, display-only, reversibel).
   Gating: **fil-flagg `/data/nap_ic_sweep`** (touch/rm — valgt i stedet for
   Params-key for å slippe params_keys.h + rebuild). Når flagget finnes
   overstyres KUN curvC2 i 0x239 med sinus ±0.001 (under rail 0.0025),
   periode ~10 s. leadDy (curvC0) og alt annet urørt. Verifisert:
   py_compile + full import i device-venv OK; flagg-fil ARMERT 2026-07-02 13:30 → sweep PÅ ved neste tur (Svein slipper ssh under kjøring).
   - **Arm:** `ssh c3 "touch /data/nap_ic_sweep"` (før turen; plukkes opp
     innen ~2 s også underveis)
   - **Disarm:** `ssh c3 "rm /data/nap_ic_sweep"`
   - **Backup/full revert:** `cp /data/nap_hud_module_pre_sweep_2026-07-02.py.bak
     /data/openpilot/opendbc_repo/opendbc/car/tesla/preap/hud_module.py`
     (sha256 original: f0057f57…; opendbc_repo-working-tree er nå dirty
     med vilje — dokumentert her)
   - **VIKTIG (07-02 ettermiddag):** første testtur 16:09 var UGYLDIG —
     manager forker prosessene og pre-importerer modulene ved boot
     (`feedback_manager_preimport_arv`, process.py:201), så patchen var
     ikke i minnet. **Device rebootet 07-02 ~18:20 med Sveins godkjenning;
     manager fersk, patch+flagg verifisert intakt → NESTE tur er den
     reelle testen.** Bonus-funn: devicens klokke starter hver boot på
     bogus «2025-07-02 16:04» til NTP synker → mtime-argumenter på device
     (inkl. pkl-datering tidligere i dag) er upålitelige; eliminering av
     modell-pkl står på LIVE modell-helse-data (corr +0.86), ikke mtimes.
   - **Protokoll:** kjør RETT strekning med long aktiv, se på IC-path:
     vugger side-side (~±2,5 m utslag, 10 s syklus) → pipelinen konsumerer
     vår 0x239 → re-undersøk symptomforståelse med foto i kjent sving;
     står bom stille → Buddy ignorerer 0x239-innhold → Buddy-intern.
2. **Foto/video av IC i kjent sving** (dokumentér "stuck" visuelt) — gir
   sammenligningsgrunnlag og objektivt før/etter for enhver fix.

---

## 5. KONKLUSJON 2026-07-02 kveld — SWEEP-TESTEN ER UTFØRT: MOTTAKERSIDEN BEKREFTET

Rute `00000142` (11 seg, etter reboot): transmittert 0x239-C2 var en **ren
±0.001-sinus med 10,0 s periode i 100 % av 6001 meldinger** (verifisert i
rlog; can-ekko 2338/2339 = nådde ledningen). Svein observerte **null
bevegelse i IC-path** hele turen.

Dermed, sammenholdt med at ALT annet er eliminert med data (denne fila +
korreksjonsblokk):

**Buddy/IC-mottakerkjeden konsumerer ikke DAS_lanes-innholdet lenger.**
Skilt/hastighet/MAX-pipelines (samme CAN inn, samme ethernet ut) virker;
lane-geometri-pipelinen er død/gatet. Sendersiden er hinsides tvil frisk.

Bil-side-verdidiff (mai↔nå, buss 0) viser kun døgn/miljø-felter (dato i
0x318, temp/lysstyrke-aktig i 0x208/0x308/0x246); GTW_carConfig uendret →
ingen bil-config-trigger funnet.

### GJENOPPDAGET 07-03: buddy_sprint-verktøykassen + presedens for symptomet

`scripts/buddy_sprint/` (2026-05-25, T1–T7) er en ferdig Buddy-sniffe-suite.
README-en dokumenterer at **eksakt dagens patologi var observert på Buddys
eth1 (IC-siden) allerede 05-25**: 0x239 ut mot IC = ÉN konstant payload
`7001030b80101611` (dekodet: ingen lanes, viewRange=1 — en idle/default-
frame), mens 0x399 passerte fritt (32 unike payloads). Kurvene virket
igjen 06-20 (etter trigger-felt-fiksen) → tilstanden er nå tilbake TROSS
korrekte trigger-felt (bevist på CAN denne uka).

Buddy-fakta fra sprint-README: **Pi-basert, ssh pi/pi via WiFi-AP
`tinklaAP` (10.5.5.1/24)**, prosess `tinklaBuddy`, eth0=chassis-side,
eth1=IC-side, lytter på UDP 20101 (EtherCAN-input), har web-UI.
Regel: TEMP-only på Buddy (`feedback_buddy_temp_only`). Firmware er IKKE
lokal og IKKE offentlig (BogGyver GitHub sjekket 07-03) — hentes fra boksen.

### Neste steg (Buddy-økt ved bilen, parkert)
0. Dev-boks/laptop på `tinklaAP`-WiFi (Svein).
1. **HENT SOFTWAREN FØRST** (read-only): `scp -r pi@10.5.5.1:` hjem —
   tinklaBuddy-binær/scripts (+/etc + init). Arkiver i eget repo. Så leses
   0x239/lane-håndteringen offline → finn hva som gater forwarding.
2. `t2_inventory.sh` + `t7_web_ui.sh` (read-only, <2 min).
3. `t4_dual_capture.py` med c3 på: er eth1-0x239 konstant `7001030b…` igjen?
4. Hvis konstant: `t1_sigstop.sh` → bevis at tinklaBuddy genererer den.
5. Med kildekoden i hånd: finn gate-betingelsen og hvorfor 05-25-fiksen
   virket men ikke nå.

### Neste steg (mottaker-jakt, generelt)
1. **Byte-eksakt replay av fungerende æra:** mai-rlogene inneholder Tinklas
   egne TX-ekko (src=128) — eksakte bytes + timing fra kjøringer der IC
   beviselig tegnet kurver. Replay hele DAS-strømmen på bussen og se om IC
   animerer. Eliminerer siste rest av "subtilt felt/timing"-tvil. NB: IC
   kan være speed-gatet parkert (Sveins poeng) — kun positivt resultat
   informativt parkert.
2. **Fysisk Buddy:** reseat CAN-tap + ethernet (merk: radar-kabelreparasjonen
   innebar fysisk arbeid — sjekk om Buddy-ledninger ble berørt; widgets
   virker dog, så inn/ut-banene lever). Deretter reflash/bytte av Buddy /
   kontakt Tinkla-miljøet (BogGyver) — firmware er lukket, ingen lokal kilde.
3. Foto/video-dokumentasjon av dagens rendering (før/etter-grunnlag).

### Opprydding
Sweep-flagget er FJERNET (rm /data/nap_ic_sweep) — patchen ligger inert på
device (gjør ingenting uten flagg). Full revert:
`cp /data/nap_hud_module_pre_sweep_2026-07-02.py.bak → hud_module.py` + reboot.

---

## 5. Sekundærfunn (egne saker, ikke IC-blokkerende)

1. **`carState.steeringAngleDeg` er fortegns-INVERTERT** vs openpilot-konvensjon
   (positiv=venstre): corr(steer-avledet kurvatur, IMU) = **−0.998**.
   Styringen virker (desiredCurvature-kjeden er konsistent), men alt som
   konsumerer steeringAngleDeg med standard-konvensjon (paramsd/torqued/lagd,
   fremtidig kode) bør sjekkes. UAVKLART om dette er bevisst Tinkla-arv.
2. **C2-DBC-encodingen kan aldri vise svinger krappere enn R=800 m** (clip
   ±0.0025, og NAPs ×4-skala ≙ κ≤0.00125). Norske landeveier saturerer 24–78 %
   av tiden — også i Tinkla-æraen. IC-kurvene har ALDRI vært proporsjonale på
   krappe svinger; "virket" = riktig retning + animasjon.
3. **Kompilert modell (chunked tinygrad-pkl) er eliminert:** mtimes eldre enn
   fungerende 06-20-rute, manifest-sti vinner alltid i `read_file_chunked`,
   ingen plain pkl etterlatt av StarPilot-checkouten. MEN: `*.pkl*` er
   gitignored mens StarPilot **committer** pkl med samme filnavn → et avbrutt
   checkout kan i teorien etterlate feil modell usynlig for `git status`.
   Verifiser chunk-sha ved neste fork-bytte.
4. **Loggretensjon:** kun 4 post-switch-ruter igjen på devicen (deleter),
   mens 460 Tinkla-æra-rlogs (april/mai) ligger preservert og fyller 194G.
   Vurder å preservere 00000131/136 (bevismateriale) og frigjøre mai-ruter
   etter arkivering.
5. 07-01-handoverens "6 % saturert" på 06-20-ruta: mitt 12-segment-utvalg måler
   0.306 (inkl. stillestående). Tallene er utvalgs-avhengige; bruk scriptene
   for konsistent metodikk.

---

## 6. C3-tilstand etter økten

Ingen endringer på device utover lesing + `/tmp`-scripts (ic_curve_*,
das_suite_ab, qlog_das_decode, q104_*.zst). Ingen params endret, ingen
prosesser restartet, working-tree urørt. WSL-repo: denne fila +
`scripts/nap_ic_curve_analysis/` er nye.

---

## 6. BUDDY-FIRMWARE HENTET + REVERSERT (2026-07-03)

Buddy-imaget er **direkte nedlastbart** fra `tinkla.us/files/` (wiki-DB nede,
men fil-serveren lever; lenke via Wayback av Tinkla_Buddy_Installation):
`tinklaBuddy-R2S-1.44-11.11.2022.img.gz` (4.7 GB). Arkivert lokalt i eget repo
`/home/svein/repos/tinkla-buddy-firmware` (img.gz + ekstrahert app + README).
Svein bekreftet HW = **NanoPi R2S** → dette er riktig image.

### Struktur
- p8=rootfs (Armbian base, ingen tinkla-app), p9=userdata (overlayfs upper —
  appen bor i `/root/opt/tinkla`). Lest med `debugfs` uten mount/root.
- `bin/tinklaBuddy`: MITM-kjerne, **aarch64 ELF, USTRIPPET m/ debug_info** →
  full symbolreversering mulig (capstone; `scratchpad/disas.py`).
- `scripts/*.en` = AES-kryptert bash (runtime-dekrypt via tinklaSec).
- `settings/` = 39 klartekst flat-files.

### Gating-arkitektur (reversert fra symboler + disas)
Buddy er en pakke-MITM med per-melding-håndterere:
`process_GTW_carConfig`, `process_UI_DriverAssistControls`,
`process_MCU_driverLimits`, `process_fake_das` (bygger 0x659),
`process_run_on_IC`, `should_forward` (UDP-port-ruting 20098–20101),
`process_gatewayStatus`, `process_DI_state`.

**Gating-state (styrer om IC får OP-lane-visuals):** `tinklaOPIntegration`
(master av/på), `gtw_dashw` (hvilken AP-hardware IC tror finnes; **-1 =
udetektert**), `acc_rail`/`prev_acc_rail_stat`, `drive_rails_on`/
`prev_drive_rail_on`, `tinklaMCUtype`, `dasHw`. Buddy lærer bilens dashw fra
GTW_carConfig og **emulerer AP-hardware mot IC-en** slik at IC-en rendrer
AP-visuals (inkl. lanes). Ref-imagets verdier (OP=0, gtw_dashw=-1, acc_rail=0,
platform=H5, gear=P) er FABRIKK-DEFAULT — ikke Sveins kjørende R2S-boks.

### ⚠️ KRITISK BLINDSONE avdekket
**All vår CAN-analyse (denne uka + 05-25) fanget kun chassis-siden (bus 0 /
eth0-inn). Buddys IC-side-OUTPUT (eth1, EtherCAN-over-UDP port 20101 til IC-en)
er ALDRI fanget.** Det er nettopp der Buddy kan sende stale/default `gtw_dashw`
eller idle-0x239. Sendersiden vår (C3→panda→bus 0) er bevist frisk helt frem
til Buddys inngang — men hva Buddy sender VIDERE til IC-en er uobservert.
`buddy_sprint/t4_dual_capture.py` er bygd nettopp for å fange eth1.

### NESTE (Buddy-økt ved bil, parkert, WiFi tinklaAP)
1. Les Sveins faktiske `/opt/tinkla/settings/{tinklaOPIntegration,gtw_dashw,
   acc_rail,tinklaMCUtype,dasHw,tinklaVersion}` + `bin/tinklaBuddy`-versjon
   (17-Jun-2022 i ref) — sammenlign mot arkivet. `gtw_dashw=-1` eller
   `OPIntegration≠1` UNDER kjøring = røykpistol.
2. `t4_dual_capture.py`: fang eth1 — er 0x239 mot IC den konstante idle-framen,
   og hvilken dashw/carConfig sender Buddy til IC-en?
3. Med binæren lokal: disassembler `process_GTW_carConfig` +
   `process_UI_DriverAssistControls` fullt for å utlede eksakt dashw-gate.
