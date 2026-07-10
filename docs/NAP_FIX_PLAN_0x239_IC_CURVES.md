# NAP Fix-plan — 0x239 IC-kurver (v2, 2026-07-10 kveld — ROTÅRSAK BEVIST)

**Status:** Rotårsak bevist på artefakt-nivå — se
`NAP_FINDINGS_2026_07_10_IC_ROTARSAK_BEVIST.md` (beviskjede L1–L7).
Denne planen erstatter v1-utkastet fullstendig (v1 i git-historikken).
V1s «reboot og la pandad flashe» ville vært en **no-op**: pandad verifiserer
mot den committede `panda.bin.signed`, som ER den stale kjørende binæren.

**Rotårsak:** Kjørende panda-firmware er bygget 12.–19. mai fra
MagZu-æra-kilde, FØR IC-generatoren fantes. Den stale binæren er committet i
`nap-c3-panda` og shippes av public git; pandad ser aldri mismatch. Fiksen er
å få et **gjenbygg av dagens kilde** signert, committet og flashet — helt i
tråd med kravet: permanent, i public repo, ingen device-hacks.

---

## FASE 0 — Pre-flight (før noe flashes)

Den nye binæren endrer mer enn IC (MagZu-treet → NAP F4-revive-treet er stor
kildedivergens, jf. 25k-linjers-diffen fra 07-01-økten). Kjørende binær er
empirisk trygg for kjøring; den nye er det på papiret (dagens kilde er den
sprint-reviewede NAP-koden alle trodde kjørte).

- **0.1 Diff-gjennomgang av aktuatorbaner** mellom MagZu-commit `90387239`
  (finnes i C3s panda-repo-objekter) og dagens kilde: tx_hook-grenser for
  0x488/0x2B9/0x214/0x551, rx-checks, relay-logikk. Kilden til 90387239:
  `git -C /data/openpilot/panda show 9038723938a5:<fil>` + opendbc-safety slik
  MagZu-linjen brukte den. Mål: ingen overraskelser i det som styrer bilen.
- **0.2 Kjør opendbc safety-testene** for tesla_preap lokalt
  (`opendbc_repo/opendbc/safety/tests/`) — de dekker IC-generatoren
  (introspeksjons-getterne finnes nettopp for dette).
- **0.3 Kjør provenansvakten** (baseline FØR fiks — skal FEILE på committet
  binær): `scripts/nap_fw_provenance/check_fw_provenance.py`.

## FASE 1 — Permanent fiks (repo-nivå)

1. **Bygg + signer på C3** (arm-none-eabi-gcc finnes på device):
   `ssh comma@C3 'cd /data/openpilot/panda && scons board/obj/panda.bin.signed'`
   Verifiser at `obj/panda.bin.signed` nå embedder `DEV-02f19e33-DEBUG` og
   består provenansvakten (IC-tabell til stede).
2. **Commit den nye binæren til `nap-c3-panda@main`** (deployment-modellen er
   committede binærer — behold den, men med vakt, se Fase 3):
   `board/obj/panda.bin.signed` (+ `bootstub.panda.bin` hvis endret).
   Oppdater panda-submodule-pin i `sveinmer/openpilot@main`.
3. **Flash:** restart pandad (reboot C3). pandad ser nå signatur-mismatch
   kjørende(90387239) vs fil(02f19e33) → auto-flash (`pandad.py:54`). F4-panda
   kan trenge DFU-recovery-stien (`5c63134`-commiten finnes nettopp for det).
4. **Verifiser flash:** `Panda().get_version()` → `DEV-02f19e33-DEBUG`
   (via pandad-logg / PandaSignatures-param, ikke USB-kapring mens openpilot
   kjører).

**Beslutning for Svein før Fase 1:** flash-tidspunkt (bilen hjemme, ikke i
bruk) og om 0.1-diffen godkjennes. Claude utfører ikke flash uten klarsignal.

## FASE 2 — Måling (avgjør om fiksen er tilstrekkelig)

1. **CAN bus 0:** 0x239 skal nå ha ROTERENDE counter (0..15) i tillegg til
   openpilots counter=1-originaler. Offline rlog-sjekk med eksisterende
   verktøy (`scripts/nap_ic_curve_analysis/live_2026_07_10/`). 10 Hz-takt
   styrt av 0x348.
2. **Ethernet (Buddy-siden):** blir GTWs 0x239 mot IC nå range=50/varierende
   (ikke idle range=1)? Verktøy:
   `scripts/buddy_sprint/live_2026_07_04/onroad_0x239_source.py`.
3. **IC-foto/video i kjent sving** — objektiv før/etter.

**Utfall A (kurver tilbake):** ferdig. Gå til Fase 3.
**Utfall B (rotasjon på CAN, men GTW broer fortsatt idle):** eneste
gjenværende delta mot fungerende Tinkla er duplikat-originalene → Fase 2b.

### FASE 2b — Tinkla-paritet TX-block (kun ved utfall B)
Port Tinklas semantikk 1:1 (`safety_tesla.h` `fwd_data_message`): når
IC-integration er på, **blokker openpilots original-TX** for de 8 gatede
IC-adressene etter capture (`tesla_preap.h` tx_hook ~L806: capture beholdes,
returnér `tx=false` for cache-adressene). Da eier panda-generatoren counteren
alene — nøyaktig konfigurasjonen som beviselig ga kurver. Kodeendring i
opendbc → sprint-regime: test i libsafety først (capture→emit→counter-eierskap),
så ny runde Fase 1 (bygg/sign/commit/flash) + Fase 2.

## FASE 3 — Permanent riggforbedring (så dette ALDRI skjer igjen)

1. **Provenansvakt (levert i denne økten):**
   `scripts/nap_fw_provenance/check_fw_provenance.py` —
   sammenligner committet/kjørende binær mot innholdsmarkører generert FRA
   dagens kilde (IC-adressetabellen parses ut av `tesla_preap.h`, aldri
   hardkodet). Kjøres: (a) ved sesjonsstart før CAN-feilsøking, (b) før
   commit av binærer i nap-c3-panda, (c) mot C3 med `--c3` (read-only ssh).
2. **Sesjonprotokoll-regel (kanonisert i memory):** før feilsøking av
   CAN-adferd: bevis at koden du leser er koden som kjører (provenansvakt),
   ellers er all kildelesing potensielt arkeologi i feil lag.
3. **Anbefalt oppfølging (egen beslutning):** gjør panda-versjonsstrengen
   innholdsderivert (hash av kildefil-manifest: board/ + opendbc safety) i
   stedet for cwd-avhengig git-HEAD — da blir stale artefakter synlige i
   selve versjonsstrengen. Endring i `panda/SConscript:26`.
4. **Rydding:** gjenopprett/skriv `.claude/SPRINT_PROTOCOL.md`; revert C3s
   inerte `hud_module.py`-sweep-patch; NTP/klokke-sjekk i sesjonstart
   (C3 sto på 2025 den 07-02).

## Sikkerhet
- IC-frames er display-only (risk-tier 3). Flash-operasjonen er standard
  pandad-mekanikk. Risikoen ligger i kildedivergensen for aktuatorbaner →
  derfor Fase 0.1-diffen som eksplisitt gate.
- Ingen Buddy-endringer (feedback_buddy_temp_only respekteres).

---

## FASE 0 — UTFØRT 2026-07-10 (kveld): **GO anbefalt**

**0.2 Safety-tester: GRØNN.** `opendbc/safety/tests/test_tesla_preap.py`:
**100 passed, 10 skipped** (libsafety bygget lokalt, uv + pytest). Dekker
vinkelgrenser (steer_angle_cmd_checks_vm), disengage (dør/gir/brems/gass),
pedal-gating, IC TX-gate OG hele IC-generatoren (cache-capture, 0x348-
dispatch, emission-gating, flagg av/på).

**0.1a Panda-tre-diff 90387239→02f19e33 (110 filer, +25 730/−556):**
- ~24k linjer = NYE F4-plattformfiler (vendor-headere stm32f413xx.h 15k,
  CMSIS 4k, HAL, startup-asm, linker-script, bxcan-driver, dos.h) — gjenopplivet
  plattformstøtte, ikke logikkendring.
- Delte filer: små upstream-refaktorer (can_silent → enum, include-gating per
  MCU, array-size-navn). Tesla-ignition via 0x348 på bus 0 er VIDEREFØRT og
  hardnet (counter-validering; kommentaren refererer eksplisitt MagZu-port
  fra 90387239). Irrelevant hw (jungle/sound/siren/fan-H7) utgjør resten.
- Dette forklarer også siste uforklarte binær-observasjon: gammel binær har
  2× `cmp #0x348` (ignition), ny har 4× (ignition + IC-dispatcher).

**0.1b Aktuator-konstanter på binærnivå (kjørende vs fersk main.bin):**
identisk profil — angle-offset 0x4000: 12 treff begge; angle_meas 0x2000: 18
begge; pedal-terskel 500: 8 begge; `slip_factor` −0.0005666 (float) funnet i
begge (0x9da4 / 0xa0b0). Gammel og ny firmware håndhever samme grenser.

**Restrisiko (eneste reelle):** 02f19e33-F4-binæren har aldri bootet på
bilens panda (første kjøring av F4-revive-porten). Mitigering = staged
Fase 1: flash PARKERT → sjekk pandaState/health + CAN-trafikk + 0x239-
counter-rotasjon parkert → kort testkjøring før normal bruk.
**Rollback:** gammel binær (blob `04dab0e5`) ligger i nap-c3-panda-
historikken — reflash gjenoppretter eksakt dagens tilstand.

**Konklusjon: GO for Fase 1 ved Sveins klarsignal.**
