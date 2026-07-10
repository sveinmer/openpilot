# tinklaBuddy firmware-reversering (aarch64)

Verktøy for å reversere `/opt/tinkla/bin/tinklaBuddy` (ustrippet aarch64 ELF
m/ debug_info). Brukt til å bekrefte 0x239 DAS_lanes root cause 2026-07-04
(se `docs/NAP_BUDDY_0x239_ROOTCAUSE_MERGED_2026_07_04.md`).

## ⚠️ Oppdatering 2026-07-04 (kveld): v1.49-binæren er nå committet her
`tinklaBuddy.v149` (Sveins FAKTISKE boks, hentet med `../live_2026_07_04/buddy_scp.py`)
ligger i denne mappen — du slipper å hente image/binær. Reverseringen bekreftet
at Buddy-logikken er SUNN og at latchen settes ubetinget; se
`docs/NAP_HANDOVER_2026_07_04_KVELD_0x239_UPSTREAM_GW.md`. Root-cause er oppstrøms
(`gw` 192.168.90.102), ikke Buddy. v1.49-offsets: `DAS_fakeDasReceived`@0x4d5c0c,
`process_fake_das`@0x406da0, `process_DI_state`@0x406a88.

## Oppsett (portabel laptop)
```bash
python3 -m venv revenv && ./revenv/bin/pip install capstone pyelftools
```

### Hent tinklaBuddy-binæren

**A) Fra lokalt image (raskest — ingen mount/root nødvendig, via debugfs):**
```bash
IMG=tinklaBuddy-R2S-1.44-11.11.2022.img            # dekomprimer .img.gz først
# p9 = userdata (overlayfs upper). Start-sektor fra: fdisk -l $IMG
# (i R2S-1.44-imaget: p9 start=4038656). Appen: /root/opt/tinkla.
debugfs -R "dump /root/opt/tinkla/bin/tinklaBuddy ./tinklaBuddy.v144" \
  <(dd if=$IMG bs=512 skip=4038656 2>/dev/null)   # el. dd p9 til egen fil først
```
Binæren er **ustrippet aarch64 ELF m/ debug_info** → full symbol-reversering.

**B) v1.49 fra den KJØRENDE boksen (for endelig offset-bekreftelse):**
```bash
scp pi@10.5.5.1:/opt/tinkla/bin/tinklaBuddy ./tinklaBuddy.v149   # passord: BUDDY_PASS (lokal memory)
```
Det lokale imaget er **v1.44**; Sveins boks kjører **v1.49**. Mekanismen
(process_DI_state-gate + process_fake_das-latch) er nær sikkert identisk, men
den EKSAKTE latch-bit-offset må bekreftes mot v1.49 før en openpilot-fix skrives.
Gjør all groundwork på v1.44 lokalt nå; bekreft biten mot v1.49 til slutt.

## Verktøy
- `disas.py <binær> <symbol> [...]` — disassembler navngitt(e) funksjon(er)
  m/ streng- og kall-oppløsning.
- `xref2.py <binær> <global>` — finn funksjoner som LESER vs SKRIVER en global
  (STT_OBJECT), f.eks. `DAS_fakeDasReceived`.
- `findstr.py <binær> "<streng>"` — finn hvilken funksjon som refererer en streng.

## Nøkkelfunn (v1.44-arkiv; verifiser offsets på v1.49)
- `process_DI_state` @0x406a80 — emitterer IC-0x239, gated på
  `tinklaOPIntegration==1` AND `DAS_fakeDasReceived==1` (offset 0x11c).
  Feiler gaten → "did not receive fakeDas yet, do nothing" → konstant fallback.
- `process_fake_das` @0x406d98 — SETTER `DAS_fakeDasReceived=1` (latch) når
  innkommende fakeDAS-frame passerer bit-test på payload-byte.
- Globals: `DAS_fakeDasReceived`@0x4d3c0c, `GTW_dasHw`@0x4d2094,
  `real_DAS_enabled`@0x4d3bd0.

## Oppgave for portabel laptop
1. `xref2.py tinklaBuddy.v149 DAS_fakeDasReceived` → finn setter-funksjon.
2. `disas.py tinklaBuddy.v149 process_fake_das` → les EKSAKT latch-bit + payload-offset.
3. Map biten til `create_fake_DAS_msg` (0x659) i opendbc teslacan.py → avgjør om
   openpilot slutter å sette biten (openpilot-fix) el. Buddy-intern (gtw_dashw).

Firmware-arkiv (v1.44 img + ekstrahert /opt/tinkla) ligger lokalt utenfor repo:
`/home/svein/repos/tinkla-buddy-firmware` (for stor for git; img.gz 4.7 GB).
