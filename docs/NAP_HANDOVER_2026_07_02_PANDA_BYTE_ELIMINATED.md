# NAP Handover 2026-07-02 — Panda BYTE-eliminert, IC-curves reåpnet

**Superseder** de panda-relaterte konklusjonene i
`NAP_HANDOVER_2026_07_01_IC_CURVES_INVESTIGATION.md`. Curve-elimineringene
(kode/modell/Buddy/kalibrering) der står fortsatt. Se også
`NAP_PANDA_FIRMWARE_VERIFIED_2026_07_01.md` (chain-of-custody).

**Regel for neste agent:** ingen påstand i denne fila uten evidens ved siden av.
Der det er hypotese, står det HYPOTESE. Ikke gjenta forrige økts feil (påsto
panda-mismatch uten byte-bevis → skapte kaos).

---

## 1. HOVEDRESULTAT (byte-bevist, hvert ledd verifisert)

Forrige handover påsto: *"public panda pinnet til F4-revive 02f19e33, som er
25 468 linjer ulik fungerende Fase-7 90387239 → firmware-mismatch → switch-
problemet."* **Dette er FEIL — motbevist med hasher.**

`02f19e33` og `90387239` er to **kilde-commits**, ikke to binærer. Public-pin-
commiten heter `02f19e33`, men den committede F4-**binæren** inni er `90387239`.
25k-linjers-diffen er kilde-tre-divergens (board/driver/F4-support), ikke
binæren som shippes.

Byte-kjede (F4 `panda.bin.signed`):

| Ledd | Bevis |
|---|---|
| **LIVE kjørende panda** | `PandaSignatures`-param (128 B, sig `8c182a26…`, sha256 `0a94a741…`) == on-disk-sig → **MATCH_LIVE: True** |
| on-disk `panda/board/obj/panda.bin.signed` | git-blob `04dab0e5`, sha256 `af9b369e` |
| committet @`02f19e33` (public-pin) | git-blob `04dab0e5` (identisk) |
| GitHub `sveinmer/nap-c3-panda@main` | blob `04dab0e5`, 72920 B (identisk) |
| public `sveinmer/openpilot@main` | pinner panda → `02f19e33` |

bootstub F4: on-disk == committet == GitHub = blob `daeb5c79` (11148 B).

**→ Pandaen som kjører på bilen er byte-identisk med det GitHub public shipper.
Panda er definitivt eliminert som forskjell fra fungerende tilstand.**

### Konsekvenser
- **Public-flashbar-kravet er OPPFYLT.** Ingen re-flash, re-sync eller re-pin
  nødvendig. En ren install fra din git gir byte-identisk fungerende firmware.
- **Forrige økts anbefalte "definitive test" (rydd panda + flash rent + kjør)
  er MOOT** — den ville flashet den identiske binæren (90387239) som allerede
  kjører → kan per definisjon ikke endre kurvene. IKKE gjør den.
- **Ingen aktiv DFU-churn nå:** pandad avgjør reflash på signatur
  (`pandad.py:54,70`), live-sig == forventet → `needs_recovery=False`.
  `5c6313473`-DFU-commiten trigger ikke i nåværende tilstand.

### Red herrings som lurte forrige økter (alle inert/lokalt)
- `board/obj/version` = `DEV-02f19e33-DEBUG` på device → **GITIGNORED lokal
  build-artefakt** (siste H7-build). Shippes ikke; pandad bruker signatur, ikke
  denne fila. Ikke-autoritativ.
- Lokale `panda_h7.bin.signed` (02f19e33) + `bootstub.panda_h7.bin` (1a1f3f9c)
  er inkonsistente, men **ubrukte** (dos=F4). Ikke slett dem: `panda.cc:131`
  itererer `{panda.bin.signed, panda_h7.bin.signed}` ved innlasting.
- hw verifisert live: `pandaType: dos`; `F4_DEVICES=[WHITE,BLACK,DOS]`,
  `DEPRECATED_DEVICES=F4_DEVICES` → pandad flasher F4-target for dos.

---

## 2. IC-CURVES: status etter eliminasjon

Alle sjekkbare ledd nå bevist identiske med fungerende 06-20-rute (f511dbb72):
kode (deploy f511dbb72 → fortsatt stuck¹), modell (.onnx+metadata sha), **panda-
binær (denne økten)**, param=15, kalibrering, Buddy (signs/hastighet/MAX).

¹ "f511dbb72-deploy → fortsatt stuck" er FORRIGE ØKTS rapport, ikke re-verifisert
denne økten. Merk: den testen restaurerte openpilot-kode, ikke nødvendigvis
panda-state — men vi vet nå panda-binæren uansett er identisk.

Eneste openpilot-delta working→nå = pandad-DFU-commiten (`5c6313473`), som
forrige økt eksonerte via f511dbb72-redeploy.

### Gjenstående muligheter (HYPOTESER — ikke bevist)
- **(a) Ikke en reell regresjon / vei-avhengig.** LEDENDE ved eliminasjon.
  Working 06-20 hadde slake svinger (0x239 C2 6% saturert); "stuck"-observasjon
  på skarpere vei (C2 28% saturert). `curvC2 = clip(coefs[1]*f2, -0.0025,
  0.0025)` — skarpere vei enn clip-grensen gir saturert-til-maks = "stuck på én
  sving", uten bug. IKKE bevist; krever kontrollert observasjon.
- **(b) Nedstrøms, uinstrumentert.** Buddy-MITM sin håndtering av 0x239 LANE-
  frame *spesifikt* (skilt/hastighet = andre frames, så "Buddy virker" ≠ lane-
  forwarding virker), eller IC-render-siden. Aldri isolert.

### Blindveier (ikke prøv på nytt)
- **rlog A/B mot fungerende rute:** DØD. Public-rute har kun qlog; qlog
  desimerer bort `can`-strømmen (can=0 er artefakt). Full rlog rotert bort —
  utilgjengelig selv med Sveins bruker-JWT (bekreftet av Svein 07-02).
- **curve-math-tweaking (V46–V64e scale/bias/lane/c1):** kjørt i grus, revertert
  til Tinkla 1:1. Backups på device (`/data/nap_v4*_*hud_module*.bak`). Ikke tweak.

---

## 3. ENESTE GJENSTÅENDE DECISIVE TEST (observasjon, ikke endring)

Ingen har logget **polyfit-interne live**. Handoverens curvC-tall kom fra å
dekode 0x239-output i desimert qlog — aldri rå `coefs`/`max_idx`/`position`.

**Plan:** utvid eksisterende `NAPDebugLog` (`opendbc/car/tesla/preap/debug_log.py`,
allerede param-gated → `/data/nap_debug.jsonl`; per nå longitudinell-only, kalt
fra `carcontroller.py:154`) med et curve-record fra `hud_module.py`-polyfit-
blokka (linje 160–185): logg per tick `max_idx`, `len(x)`, rå `coefs` (alle 4),
`CS.curvC0-3`, `x[-1]`, `y[-3:]` (fjern-felt). Sett `NAPDebugLog=1`, kjør en
kjent svingete vei, hent `/data/nap_debug.jsonl`.

**Splitter definitivt:**
- curvC varierer korrekt med veien → problemet er (b) Buddy/IC/persepsjon.
- curvC går faktisk stuck/saturert → oppstrøms; se om fjern-felt-`position`-støy
  dominerer full-array-fit-en (`get_path_length_idx(y,100)` returnerer alltid
  full array fordi y=lateral ≪100 — delt med Tinkla, men modellen er nyere).

Dette er OBSERVASJON, distinkt fra V46–V64-curve-math-eksperimentene. Trenger
device-patch under kjøring (koordiner med Svein + bil).

---

## 4. C3-TILSTAND NÅ (verifisert 2026-07-02)
- branch `main` @ `5c631347308`, working-tree ren, openpilot kjører (manager/ui/
  pandad), `safetyModel: noOutput, safetyParam: 0` (ikke armed — bil av).
- Live panda = F4 Fase-7 (sig `8c182a26…`), byte-identisk med GitHub. Urørt.
- WSL-repo `/home/svein/repos/openpilot`: branch `dev` @ `1c2de190c` (1 foran).
  Uncommitted: `params_keys.h` + `manager.py` = `NAPTinklaICIntegration` default-på
  (urelatert til bugen, trygt). Untracked `docs/` (denne + firmware-doket + 06-28/07-01).

## 5. REPRODUSERBAR METODE (så neste agent kan re-verifisere alt over)
- **Live panda-sig:** på C3, `python3`: `Params().get("PandaSignatures")` vs
  `Panda.get_signature_from_firmware("panda/board/obj/panda.bin.signed")` (PYTHONPATH
  inkl. `/data/openpilot/panda`). Match → live==on-disk.
- **Blob-kjede:** `git rev-parse <commit>:board/obj/panda.bin.signed` (device panda repo)
  vs GitHub `curl -s api.github.com/repos/sveinmer/nap-c3-panda/contents/board/obj/panda.bin.signed?ref=main`.
- **hw-type:** `pandaStates[0].pandaType` via cereal SubMaster.
- C3: `ssh c3` → `comma@192.168.0.65`. Dongle `2f2134836e3ab8f0`.
