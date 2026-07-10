# NAP Overlevering 2026-07-10 — IC-kurver: UAVKLART + Sveins kritikk av analysen

## ⚠️ SVEINS DOM (skal stå først, uredigert)

Svein anser denne analysen som **IKKE god nok**. Konkret, med hans egne ord som
utgangspunkt:

- **«Fremmed panda (som jo også var bitlik)»** — panda-koden ble rapportert
  bit-lik med det som virket. En bit-lik firmware kan da IKKE samtidig være
  «fremmed» / mangle IC-emit. «Fremmed firmware»-konklusjonen selvmotsier
  bit-lik-premisset.
- **«Er det kineserne da?»** — «fremmed firmware 90387239» leser som en
  bortforklaring/ekstern syndebukk, ikke et bevis.
- **«Eller skal jeg bare stole på deg?»** — analysen har hoppet mellom for mange
  hypoteser uten å lande med bevis. Svein skal ikke måtte stole på påstander;
  han skal ha verifiserbare fakta.
- **Krav:** en ekte, BEVIST rotårsak + permanent fiks i public `sveinmer/openpilot`.
  Ingen kode-injeksjoner / device-hacks (de var rotårsaken til uføret).

**Dette er en berettiget kritikk. Claude (analytiker) overtolket en git-hash-
forskjell til «fremmed firmware». Det er en slutning, ikke et bevis.**

## 1. Hva som FAKTISK er bevist (direkte målt, Svein kan reprodusere selv)

Verktøy: `scripts/nap_ic_curve_analysis/live_2026_07_10/`. C3 @ 192.168.0.65
(comma@, nøkkel), Buddy @ 10.5.5.1 (pi/pi, kun Tinkla-nett).

- **openpilot sender 0x239 range=50 på CAN bus 0** — frisk lane-data (engasjert
  lat+long rute 00000171, uniq=383; + parkert). Reproduserbart offline på rlog.
- **0x239 på CAN har KUN counter={1}** (212/212 frames i 00000171). Ingen
  counter-rotasjon. Dvs. panda-re-emitteren legger IKKE til en rotert-counter-
  kopi. `byte7>>4` = 1 konstant.
- **Tinkla-æra rlog (2026-04-30, kurvene VIRKET): 0x239 counter ROTERTE**
  (byte7 = 0x20, 0xf0, …).
- **Tesla GTW (.102=gw) sender idle 0x239 (range=1) til ethernet**; broer status-
  frames (0x659/0x399/0x389) korrekt. Buddy (.103=ape) forwarder GTW's idle
  byte-identisk. (Buddy /etc/hosts: .100=cid .101=ic .102=gw .103=ape.)
- **GTW_status 0x348 (IC-trigger) ankommer** panda på bus 0.
- **Panda `get_version()` = `DEV-90387239-DEBU`; bygget firmware `obj/version`
  = `DEV-02f19e33-DEBUG`.** Git-hash-strengene er ulike. C3-openpilot = commit
  5c63134; opendbc = fb7bf3a med ÉN uncommittet fil: `hud_module.py`
  (07-02 sweep-instrumentering, INERT — flagget `/data/nap_ic_sweep` er fjernet).

**Det ENESTE solide om årsak: panda produserer ikke en rotert-counter 0x239.
Tinkla gjorde. Alt utover dette er uverifisert.**

## 2. Hva som IKKE er bevist (spekulasjon — behandles som ÅPENT)

- ❌ At firmware 90387239 «mangler» IC-emit. Git-hash ≠ funksjonelt innhold. En
  DEV-DEBUG-build kan ha annen hash og være bit-lik kode. **Ikke inspisert.**
- ❌ At counter-rotasjon er det GTW/IC krever for å vise kurver. **Antatt.**
- ❌ At re-flash av 02f19e33 gjenoppretter kurvene. **Ikke testet.**
- ❌ At bilen/GTW ikke har endret seg (sannsynlig, men ethernet-siden er aldri
  målt fra da det virket — ingen før-baseline på ethernet).
- ❌ «Tinkla bus64/src=192 vs NAP bus0» — krysser fork-grense, NAP-06-20-rlog
  slettet → aldri ren NAP-vs-NAP.

## 3. Full ærlighet: hypotese-historikken (hvorfor Svein er skeptisk)

Analysen skiftet syndebukk flere ganger, hver gang presentert med for stor
selvsikkerhet, hver gang senere nedgradert:
1. «Buddy MITM-erstatter 0x239» → motbevist (Buddy forwarder bare).
2. «fakeDas-latch=0» → motbevist (latch=1 live).
3. «Buddy dashw-feilemulering» → utelukket (IC får AP1).
4. «Tinkla bus64/APE-kanal» → svakt (fork-kryssing).
5. «Fremmed panda-firmware» → **selvmotsier bit-lik-premisset (denne kritikken).**

Det ene stabile, målte faktumet gjennom alt: **panda IC-emit produserer ikke
rotert-counter 0x239.** Resten er tolkning som ikke har landet.

## 4. Hva som MÅ til for å BEVISE rotårsak (ikke mer gjetting)

**A. Avgjør firmware-spørsmålet DEFINITIVT (ikke via git-hash):**
- Dump den KJØRENDE panda-firmwaren og sjekk om IC-emit-koden fysisk er der:
  søk binæren etter 0x348-trigger-logikken / `preap_ic`-mønstre, ELLER sammenlign
  mot lokalt bygget `panda.bin`. Hvis IC-emit-koden ER i den kjørende firmwaren →
  «fremmed firmware» er FEIL (Sveins poeng bekreftes), og årsaken er RUNTIME.
- Sammenlign `get_signature()` mot bygget `panda.bin.signed` (riktig sti). Lik
  signatur = bit-lik firmware = «fremmed»-teorien er død.

**B. Hvis firmwaren ER bit-lik (Sveins premiss holder) → finn runtime-grunnen:**
- Hvorfor kaller ikke `preap_ic_send_messages` → `preap_ic_emit_message` ut en
  rotert 0x239? Kandidater: cache aldri `valid` (capture_tx kjører ikke fordi
  openpilots 0x239 ikke treffer tx_hook-capture-stien), eller
  `preap_has_ic_integration` false i praksis tross safety_param=15.
- Instrumenter panda MINIMALT og reversibelt (debug-teller på emit), ELLER les
  panda-intern state hvis eksponert. Dette er diagnostikk, ikke en fiks.

**C. Først når A/B gir et BEVIST brudd → skriv permanent kode-fiks i repoet.**
Ikke før. Fiksen skal være i `sveinmer/openpilot` (opendbc/panda-kilde), ikke en
device-patch. Referanse for korrekt oppførsel: `/home/svein/repos/Tinkla`
(safety_tesla.h `teslaPreAp_send_IC_messages` + `teslaPreAp_generate_message`;
HUD_module.py) — den fungerende implementasjonen å porte 1:1 mot.

## 5. Kjent forskjell Tinkla↔NAP (verifiser om den betyr noe — IKKE anta)
- Tinkla `tx_hook`: `fwd_data_message()` fanger openpilots IC-frame til cache OG
  BLOKKERER original TX (`tx=false`) → kun panda-re-emit (rotert) på bussen.
- NAP `tx_hook` (tesla_preap.h ~L811): `preap_ic_capture_tx()` fanger til cache
  men BLOKKERER IKKE → openpilots direkte TX (counter=1) sendes.
- Tinkla `generate_message`: valid-sjekk UTKOMMENTERT (emitter uansett).
  NAP `preap_ic_emit_message` (~L465): `if (!cache.valid) return;`.
- **Om disse forskjellene forklarer død IC-emit er IKKE bevist** — de er
  kandidater å teste under punkt B, ikke en konklusjon.

## 6. Rydding (uavhengig av rotårsak)
- Revert C3s uncommittede `hud_module.py` sweep-patch (inert, men urent):
  `cd /data/openpilot/opendbc_repo && git checkout opendbc/car/tesla/preap/hud_module.py`
  (bekreft med Svein først; backup i 07-02-handover).

## 7. Tilgang / verktøy
- C3: `ssh comma@192.168.0.65` (hjemme) / `10.5.5.125` (Tinkla-nett), nøkkel-auth.
  cereal: `PYTHONPATH=/data/openpilot /usr/local/venv/bin/python` fra `/data/openpilot`.
- Buddy: `10.5.5.1` pi/pi (kun Tinkla-nett), AF_PACKET (ingen tcpdump).
- Tinkla-referansekode: `/home/svein/repos/Tinkla`. Replay-rig: `/home/svein/repos/nap-replay-rig`.
- Rlogs: `/data/media/0/realdata/` (NAP nummer-stil 07-08→; Tinkla dato-stil 04-30→05-08).
- Verktøy denne økten: `scripts/nap_ic_curve_analysis/live_2026_07_10/`.
