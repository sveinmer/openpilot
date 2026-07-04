# NAP Handover — 2026-06-28

**Dato:** 2026-06-28  
**Session-fokus:** C3-tilkoblings-diagnose og IC-linjer ikke-fungerende  
**Lokal branch:** `dev` på `/home/svein/repos/openpilot`

---

## TL;DR

C3 er koblet til og kjører. `switch.ps1 -Tesla` ble kjørt tidligere og byttet C3
fra `nap-c3-dev` → `main`. IC-integrasjonen (Tinkla DAS-meldinger) er konfigurert
riktig i params, men IC-linjer er ikke verifisert med bilen på. Neste steg: test
med bilen PÅ, og vurder om C3 skal byttes tilbake til `nap-c3-dev`.

---

## 1. C3-tilstand

| Parameter | Verdi |
|---|---|
| SSH-alias | `ssh c3` → `comma@192.168.0.65` |
| SSH-nøkkel | `~/.ssh/id_ed25519` |
| AGNOS-versjon | `12.6` (kernel 4.9.103) |
| C3 aktiv branch | `main` |
| C3 HEAD | `5c631347308` — pandad: auto-recover via DFU when panda.flash() can't enter bootstub |
| Lokal HEAD (`dev`) | `1c2de190c` — feat(sentryd): sentry-mode core |
| Panda firmware | `DEV-02f19e33-DEBUG` |
| Panda-type | `dos` (H7) |
| Ignition | `false` (bilen var av under diagnose) |
| opendbc_repo på C3 | `fb7bf3a` — snapshot 2026-05-30_1144 |

---

## 2. Funn: switch.ps1 -Tesla ble kjørt

**Bevis på C3:**
- Remote heter `fork` (ikke `origin`) — scriptet gjør `git remote remove origin`
- Aktiv branch er `main` — scriptet gjør `git checkout -f -B main fork/main`
- `NAPForcePreAP=1` — Tesla-profilen i scriptet setter nettopp dette

**Konsekvens:**
- C3 er på `main`-branchen (NAP snapshot 2026-05-30), IKKE `nap-c3-dev`
- `nap-c3-dev` på C3 er på commit `e3f5ed2ab27` (V59 H1-fix) — én commit
  foran `main`-snapshotet i opendbc
- opendbc-committen i `nap-c3-dev` (`50b7f11c789`) er IKKE hentet ned lokalt på C3
- Updater feiler med `git fetch origin main` — forventet, `origin` ble slettet av scriptet

---

## 3. IC-integrasjon (Tinkla DAS-meldinger)

### Params på C3 (alle korrekte):

```
NAPTinklaICIntegration: 1  ← IC-integrasjon AKTIVERT
NAPPedalEnabled:        1
NAPForcePreAP:          1
NAPRadarEnabled:        1
NAPPedalCalibDone:      1
```

### Kode-tilstand:

- `hud_module.py` har V59-fix (fjernet leadsData-clamp-blokk) ✓
- `carcontroller.py._update_preap()` dispatcher `hud_controller.update()` riktig ✓
- `carstate.py` leser `NAPTinklaICIntegration` fra Params ved init ✓
- DAS_LANES (0x239), DAS_STATUS (0x399) etc. er implementert ✓

### Mulig forklaring på "ingen linjer":

1. **Bilen var av** under diagnose — IC-integrasjonen sender bare DAS-meldinger
   når `ignitionLine=true` og openpilot er aktivt. Ikke mulig å verifisere i session.
2. **Main vs nap-c3-dev** — `main` bruker eldre opendbc (`fb7bf3a`) enn
   `nap-c3-dev` (`50b7f11c789`). Begge har V59-fix, men `50b7f11` kan ha
   ytterligere oppdateringer som ikke er i snapshotet.
3. **Panda firmware mismatch** — panda kjører `DEV-02f19e33-DEBUG`. Pandad
   DFU-committen ble lagt til nettopp fordi `panda.flash()` hadde problemer.
   Kan være at panda ikke er korrekt flashet.

---

## 4. CAN-bus-tilstand (fra swaglog, bil av)

```json
canState0: { totalRxCnt: 32632025, canCoreResetCnt: 112 }  ← chassis (normal)
canState1: { errorPassive: true, transmitErrorCnt: 128,
             canCoreResetCnt: 394 }                         ← autopilot-party (ACK-feil, bil av = normalt)
canState2: { transmitErrorCnt: 80, canCoreResetCnt: 252 }   ← pt-bus (ACK-feil, bil av = normalt)
spiErrorCount: 32768                                        ← akkumulert, kan være norm
```

Høye `canCoreResetCnt` på bus1/2 er **forventet** når bilen er av — ingen node
acker meldingene. Ikke grunnlag for alarm uten bil-på-sjekk.

---

## 5. Lokalt repo (`dev`-branch)

Lokal `dev`-branch er **1 commit foran** det som er pushet til C3 og GitHub `main`:

```
1c2de190c feat(sentryd): sentry-mode core — status-rapport + Nabu Casa-bro
5c6313473 pandad: auto-recover via DFU   ← C3 er her (main)
```

Sentryd-commit er ikke pushed til GitHub ennå, og ikke på C3.

---

## 6. Neste steg (prioritert)

### A) Test IC-linjer med bilen på (verifisering)

Med bilen på og openpilot aktivt:

```bash
# Fra WSL:
ssh c3 "candump -n 50 can0 2>/dev/null | grep -E '239|309|399'"
# Skal se: 239=DAS_LANES, 309=DAS_OBJECT, 399=DAS_STATUS
```

Ser ingen av disse → IC-integrasjon sender ikke. Da er det kode/panda-problem.

### B) Vurder å bytte C3 tilbake til nap-c3-dev

Hvis `main`-snapshotet har en bug som ikke er i `nap-c3-dev`:

```bash
ssh c3 "cd /data/openpilot && git checkout nap-c3-dev"
# OBS: opendbc_repo er da pekende på 50b7f11c789 som ikke er hentet ned.
# Kjør i tillegg:
ssh c3 "cd /data/openpilot && git submodule update --init opendbc_repo"
```

### C) Push sentryd-commit til C3 (valgfritt)

Lokal `dev` har sentryd-feature. Når klar:

```bash
git push fork dev:main  # fra lokal repo, mot fork-remote
# Deretter på C3:
ssh c3 "cd /data/openpilot && git fetch fork main && git checkout main && git merge fork/main"
```

### D) Sjekk panda-firmware (hvis IC-linjer fortsatt mangler)

```bash
ssh c3 "cat /data/openpilot/panda/board/obj/version"
# Forventer: release-build (ikke DEBUG) for produksjonskjøring
```

---

## 7. Viktige referanser

| Fil | Formål |
|---|---|
| `~/.ssh/config` → `Host c3` | SSH-alias til 192.168.0.65 |
| `/data/params/d/NAPTinklaICIntegration` | IC-integrasjon toggle (1=on) |
| `/data/openpilot/opendbc_repo/opendbc/car/tesla/preap/hud_module.py` | DAS-meldings-generator |
| `/data/openpilot/opendbc_repo/opendbc/car/tesla/carcontroller.py:167` | IC-dispatch i carcontroller |
| `scripts/switch.ps1 -Tesla` | Fork-bytter (kjøres fra Windows/PowerShell) |
