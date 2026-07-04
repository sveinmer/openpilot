# tinklaBuddy firmware-reversering (aarch64)

Verktøy for å reversere `/opt/tinkla/bin/tinklaBuddy` (ustrippet aarch64 ELF
m/ debug_info). Brukt til å bekrefte 0x239 DAS_lanes root cause 2026-07-04
(se `docs/NAP_BUDDY_0x239_ROOTCAUSE_MERGED_2026_07_04.md`).

## Oppsett (portabel laptop)
```bash
python3 -m venv revenv && ./revenv/bin/pip install capstone pyelftools
# hent Buddys FAKTISKE binær (v1.49) fra boksen — versjon avviker fra
# firmware-arkivets v1.44, så bit-offset MÅ leses fra live-binæren:
scp pi@10.5.5.1:/opt/tinkla/bin/tinklaBuddy ./tinklaBuddy.v149   # pass: pi
```

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
