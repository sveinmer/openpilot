# NAP Findings 2026-07-10 (kveld) — IC-kurver: ROTÅRSAK BEVIST på artefakt-nivå

**Superseder:** «fremmed firmware»-hypotesen i
`NAP_FIX_PLAN_0x239_IC_CURVES.md` (oppdatering 2026-07-10),
UAVKLART-statusen i `NAP_OVERLEVERING_2026_07_10_IC_KURVER_UAVKLART.md`,
og **panda-elimineringen** i `NAP_HANDOVER_2026_07_02_PANDA_BYTE_ELIMINATED.md`
+ `NAP_PANDA_FIRMWARE_VERIFIED_2026_07_01.md` (byte-kjeden der er korrekt målt,
men konklusjonen «panda eliminert» er feil — se §4).

Alle bevis i dette dokumentet er direkte målt. Hver lenke har kommandoen som
reproduserer den. Ingen ledd er tolkning.

---

## 1. KONKLUSJON

**Pandaen kjører en firmware bygget 12.–19. mai 2026 fra MagZu-æra-kilde —
FØR panda-IC-generatoren ble skrevet (sprint 2026-05-25). Generatoren har
aldri kjørt på bilen.** Den stale binæren ble committet inn i
`nap-c3-panda`-snapshotet 2026-05-30 som `board/obj/panda.bin.signed`, og
shippes siden av public git. pandad verifiserer kjørende firmware mot nettopp
denne fila → signatur matcher alltid → aldri reflash. Kilden er bit-lik
(Sveins premiss VAR korrekt), artefakten er gammel. Ikke fremmed firmware,
ikke kineserne, ikke bil-byttet: **en stale, selv-konsistent build-artefakt
kanonisert i git.**

Den korrekte firmwaren (med IC-generator) ligger allerede ferdigkompilert på
C3 som `obj/panda/main.bin` (bygget 2026-07-02) — men sign-steget kjørte
aldri, så den nådde aldri `panda.bin.signed` og dermed aldri flash.

## 2. BEVISKJEDE (hvert ledd reproduserbart)

**L1. Kjørende firmware == on-disk/committet `panda.bin.signed`.**
Embedded versjonsstreng i binæren = `DEV-90387239-DEBUG` = det panda
rapporterer live. RSA-sig-kjeden fra 07-01-dokumentet (MATCH_LIVE: True)
bekrefter samme.
`ssh comma@C3 'strings -a /data/openpilot/panda/board/obj/panda.bin.signed | grep DEV-'`

**L2. `90387239` er en panda-repo-commit, ikke en fremmed hash.**
`git -C /data/openpilot/panda log -1 9038723938a53e2a87956048f9cacab22fc94e5e`
→ **«Add HW_TYPE_DOS (0x06) for C3 F4 internal panda», 2026-04-17, fra
MagZu/panda** (klonet på C3 2026-05-12). Versjonsstrengen genereres av
`git rev-parse --short=8 HEAD` i byggeprosessens cwd (`panda/SConscript:26-31`)
→ binæren ble bygget mens panda-repoet sto på denne commiten.

**L3. Byggevinduet er 2026-05-12 → 2026-05-19.**
`git -C /data/openpilot/panda reflog --date=iso`:
checkout TIL 90387239 kl 2026-05-12 22:26, checkout BORT 2026-05-19 19:34.
Panda-HEAD var aldri der igjen. IC-generator-sprinten er datert 2026-05-25
(kildekommentar `tesla_preap.h:360`), opendbc-snapshot med generatoren er
2026-05-30. **Binæren er eldre enn koden den skulle inneholde.**

**L4. Binærinnhold (atom-nivå): kjørende firmware MANGLER IC-generatoren.**
Disassemblering (capstone, thumb) + råbytesøk av `panda.bin.signed`:
- `PREAP_IC_CACHE_ADDRS`-tabellen (20 bytes, uint16 LE:
  239 03A9 0309 03B1 0399 0389 03E9 0329 0369 0349): **IKKE funnet**,
  heller ikke delvis (0 vinduer med ≥5 av adressene).
- Kun 5/11 IC-relaterte konstanter i kode (mønsteret matcher den ELDRE
  TX-gaten), alle kontroll-konstanter (0x370/0x2B9/0x488/0x552) til stede
  (positiv kontroll på metoden).

**L5. Positiv kontroll: `obj/panda/main.bin` (bygget 2026-07-02) HAR generatoren.**
Samme skanner, samme metode: tabellen funnet på offset 0x9ec0, **11/11**
konstanter inkl. dispatcher-sekvensen, embedded `DEV-02f19e33-DEBUG`.
→ Metoden skiller riktig, og den korrekte binæren eksisterer allerede — den
ble bare aldri signert (`panda.bin.signed`-target i `SConscript:124` kjørte
ikke / fullførte ikke 07-02).
Verktøy: `scripts/nap_fw_provenance/check_fw_provenance.py`.

**L6. Runtime-miljøet var korrekt hele tiden (rlog 00000171, 07-10):**
615 pandaStates-events: én panda (`dos`/F4), `safetyModel=teslaPreap`,
`safetyParam=15` (IC-flagg bit 8 satt), controlsAllowed=True i 215 samples,
0 safetyTxBlocked. 0x348 ankommer bus 0 (live-målt tidligere samme dag).
**Alle software-gates åpne — det som manglet var selve koden i flash.**

**L7. Live-symptomet matcher eksakt:** 0x239 på CAN har KUN counter={1}
(openpilots direkte TX; NAP blokkerer ikke originalen). Rotert-counter-kopien
som generatoren skulle lagt til finnes ikke — fordi generatoren ikke finnes
i flash. Tinkla-æra (04-30, virket) hadde rotasjon fordi Tinkla-pandaen HAR
emit-koden.

## 3. KORREKSJON av «APE-kanal/bus64»-teorien

Tinklas fungerende forward-tabell (`Tinkla/panda/board/safety/safety_tesla.h:242`,
`TESLA_PREAP_FWD_MODDED`) har `fwd_to_bus=0` for 0x239 — **Tinkla emitterte
også på CAN bus 0.** «src=192/bus64» i ethernet-capturen er EtherCAN-framing
på GTW-siden, ikke en annen fysisk buss. NAPs valg av bus 0 er altså
Tinkla-paritet. Reell gjenstående forskjell mot Tinkla: Tinkla **blokkerer
openpilots original-TX** (`fwd_data_message` → `tx=false`) og eier dermed
counteren alene; NAP slipper originalen (counter=1) gjennom i tillegg.

## 4. HVORFOR FIRE ØKTER BOMMET (prosess-rotårsak)

07-01/07-02-øktene målte korrekt at kjørende == disk == git-blob `04dab0e5`
— og konkluderte «panda eliminert». Feilen: **kjeden var selv-referensiell.**
Binæren de verifiserte custody på var selv den stale artefakten, committet i
repoet. Ingen sammenlignet den committede binæren mot et **gjenbygg av den
committede kilden** — sammenligningen som feller den (L4 vs L5) tar under et
minutt med riktig verktøy. `obj/version`-mismatchen (`02f19e33` vs kjørende
`90387239`) ble avskrevet som «inert artefakt» — den var i virkeligheten
røyken fra brannen: versjonfilene skrives ved hver scons-parse
(`SConscript:163-169`), binæren re-linkes bare når bygget fullfører.

**Læring (kanonisert i memory):**
1. «Bit-lik kilde» beviser ingenting om kjørende artefakt. Verifiser
   artefakten mot et gjenbygg av kilden, eller mot innholdsmarkører fra
   kilden — aldri mot seg selv.
2. En committet binærartefakt i git er en fryst påstand om fortiden.
   Selvkonsistens (live==disk==git) er forventet også når alt er galt.
3. Versjonsstreng basert på git-hash + cwd er provenans-teater: den daterer
   checkout, ikke innhold.

## 5. HVA SOM IKKE ER BEVIST (ærlig scoping)

- At flash av korrekt firmware alene bringer kurvene tilbake. Firmware-fiksen
  er **nødvendig** (uten generator kan design ikke virke), ikke bevist
  **tilstrekkelig**: GTW må akseptere/broe rotert 0x239 fra bus 0, og
  duplikat-spørsmålet (counter=1-originaler interleaved med roterte) er en
  reell forskjell fra Tinkla. Avgjøres av Fase-2-målingene i fix-planen.
- Hvorfor 07-02-bygget stoppet før sign-steget (avbrutt/feilet — uinteressant
  for fiksen; sign-steget kjøres eksplisitt i fiksen).

## 6. RYDDING notert underveis

- `.claude/SPRINT_PROTOCOL.md` refereres av CLAUDE.md men finnes ikke i repoet.
- `docs/NAP_FIX_PANDA_IC_GENERATOR_SPRINT.md` refereres av `tesla_preap.h:360`
  men finnes ikke i docs/.
- C3: uncommittet inert `hud_module.py` sweep-patch (kjent, revert med Svein).
- C3-klokka sto på år 2025 under 07-02-økten (obj-mtimes «Jul 2 2025») —
  vurder NTP-sjekk i sesjonsprotokoll.
