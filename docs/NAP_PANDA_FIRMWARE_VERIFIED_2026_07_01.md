# NAP Panda Firmware — verifisert sannhet (2026-07-01)

**Formål:** Forhindre gjentakelse av villedelsen som kostet 2026-06-28→07-01-øktene.
Panda-firmwaren er IKKE ødelagt. Dette dokumentet forankrer chain-of-custody
med harde hasher, og forklarer red herrings-ene.

---

## TL;DR

Public git shipper den **byte-identiske** F4-firmwaren som kjører og virker på
bilen. En ren install fra `sveinmer/openpilot@main` gir nøyaktig den fungerende
firmwaren. Alt "02f19e33 vs 90387239 mismatch" stammer fra **inerte lokale
build-artefakter på C3**, ikke fra det som shippes.

---

## Hardware → firmware-valg

- Comma 3 intern panda = **`dos`** (verifisert live: `pandaType: dos`).
- `dos` er **F4** (`F4_DEVICES = [HW_TYPE_WHITE, HW_TYPE_BLACK, HW_TYPE_DOS]`,
  `DEPRECATED_DEVICES = F4_DEVICES`).
- pandad flasher derfor **F4-target = `board/obj/panda.bin.signed`** (+ `bootstub.panda.bin`),
  IKKE H7-targetene. H7-filene (`panda_h7.*`) er irrelevante på comma 3.

## Verifisert chain-of-custody (F4 boot-kjede)

| Ledd | `panda.bin.signed` (git-blob / sha256) | `bootstub.panda.bin` |
|---|---|---|
| GitHub `sveinmer/nap-c3-panda@main` | blob `04dab0e5` (72920 B) | blob `daeb5c79` (11148 B) |
| Public `openpilot@main` panda-pin | commit `02f19e33…` (= panda main) | — |
| Device committet @`02f19e33` | blob `04dab0e5` | blob `daeb5c79` |
| Device on-disk `panda.bin.signed` | blob `04dab0e5` / sha256 `af9b369e…` | blob `daeb5c79` / `6b268ec3…` (sha256) |
| **LIVE kjørende panda** (RSA-sig) | 128 B `8c182a26…` / sha256 `0a94a741…` = on-disk-sig | — |

Alle ledd byte-identiske. F4 main + bootstub er innbyrdes konsistente (begge
kildebeskrevet `DEV-90387239`, health packet v18). `git blob` = `git hash-object`.

**Live-leddet (det forrige økter ikke fikk lest):** `PandaSignatures`-param
(`selfdrive/pandad/pandad.py:152` = `panda.get_signature()` fra kjørende panda)
== `Panda.get_signature_from_firmware('panda/board/obj/panda.bin.signed')`
(pandad.py:23, forventet). Verifisert på device: **MATCH_LIVE: True**. Dermed er
"live == on-disk" bevist, ikke utledet. panda_h7-sig matcher IKKE (dos=F4).

## Red herrings (det som lurte forrige økter)

1. **`board/obj/version` = `DEV-02f19e33-DEBUG`** på device.
   → **GITIGNORED lokal build-artefakt** (skrevet av siste H7-build-forsøk).
   Shippes ikke. pandad bruker **signatur** (siste 128 B RSA-sig i `.bin.signed`),
   ikke denne fila, for flash-beslutning. **Ikke-autoritativ. Ignorer den.**
2. **Lokale `panda_h7.bin.signed` (`DEV-02f19e33`) + `bootstub.panda_h7.bin`
   (`DEV-1a1f3f9c`)** på device er inkonsistente — men er **ubrukte lokale
   H7-build-artefakter**, ikke committet, ikke shippet, irrelevante for `dos`/F4.
   Ikke slett dem blindt: `selfdrive/pandad/panda.cc:131` itererer
   `{panda.bin.signed, panda_h7.bin.signed}` ved firmware-innlasting.
3. **"90387239 vs 02f19e33" er to KILDE-commits**, ikke to binærer. Public-pin-
   commiten heter `02f19e33` (F4-revive-kildetre) men **den committede F4-binæren
   inni er `DEV-90387239`** (blob `04dab0e5`). Handoverens 25k-linjers diff er
   kilde-tre-divergens (board-support), ikke binæren som shippes.

## Branch-topologi (panda-submodul, `sveinmer/nap-c3-panda`)

- `main` = `dev` = **`02f19e33`** (public-snapshot; det `.gitmodules` pinner).
- `nap-c3-dev-f4-rebuild` tip = `1a1f3f9c` (F4-revive-fikser; `90387239` er ancestor).
- Alle disse committer **samme** F4-binær (`04dab0e5` / `af9b369e`).

## Konklusjon for public-install-kravet

**Oppfylt.** Panda-firmware trenger ingen re-flash, re-sync eller re-pin.
`build_panda_fw.sh` bygger korrekt bootstub+main sammen hvis rebuild trengs
(F4-branch `nap-c3-dev-f4-rebuild`), men det er ikke nødvendig nå.

## Konsekvens for IC-curves-regresjonen

Panda-binæren er eliminert som årsak (byte-identisk med fungerende tilstand).
Stuck-curves-symptomet er dermed **uforklart av panda**. Se
`NAP_HANDOVER_2026_07_01_IC_CURVES_INVESTIGATION.md` — handoverens eget forbehold
(curvC-forskjell kan være vei-avhengig, ikke regresjon) blir mer sannsynlig.

---

**Metode (reproduserbar):**
- Live hw-type: `pandaStates[0].pandaType` via cereal SubMaster på C3.
- Blob-ID: `git cat-file -p <commit>:board/obj/panda.bin.signed | sha256sum`;
  `git rev-parse <commit>:<path>` for git-blob.
- GitHub: `curl -s https://api.github.com/repos/sveinmer/nap-c3-panda/contents/board/obj/panda.bin.signed?ref=main`.
- Live on-disk: `git hash-object board/obj/panda.bin.signed` i `/data/openpilot/panda`.
