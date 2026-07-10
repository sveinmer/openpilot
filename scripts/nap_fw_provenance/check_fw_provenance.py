#!/usr/bin/env python3
"""NAP firmware-provenansvakt.

Beviser (eller feller) at en panda-firmware-binær er bygget fra dagens
opendbc-safety-kilde, ved å søke etter innholdsmarkører som genereres FRA
kilden ved kjøring — aldri hardkodet her:

  - PREAP_IC_CACHE_ADDRS-tabellen i tesla_preap.h kompileres som .rodata:
    en sammenhengende uint16 LE-sekvens. Finnes den ikke i binæren, er
    binæren ikke bygget fra denne kilden.
  - Embedded versjonsstreng (DEV-/RELEASE-…) rapporteres for datering.

Bakgrunn: 2026-07-10 ble det bevist at C3 kjørte firmware bygget 12.–19. mai
(før IC-generatoren fantes), fordi den stale binæren var committet i
nap-c3-panda og pandad verifiserer mot nettopp den fila (selv-referensiell
kjede). Se docs/NAP_FINDINGS_2026_07_10_IC_ROTARSAK_BEVIST.md.

Bruk:
  check_fw_provenance.py                    # sjekk committet panda.bin.signed
  check_fw_provenance.py --binary FIL       # sjekk vilkårlig binær
  check_fw_provenance.py --c3 comma@HOST    # sjekk C3 on-disk (read-only ssh)

Exit: 0 = binær(er) inneholder kildens markører, 1 = stale/drift, 2 = feil.
Kjør ved sesjonsstart før CAN-feilsøking, og før commit av binærer i
nap-c3-panda. Regel: bevis at koden du leser er koden som kjører.
"""
import argparse
import hashlib
import re
import struct
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TESLA_PREAP = REPO / "opendbc_repo/opendbc/safety/modes/tesla_preap.h"
COMMITTED_FW = REPO / "panda/board/obj/panda.bin.signed"
C3_FW = "/data/openpilot/panda/board/obj/panda.bin.signed"
C3_MAIN = "/data/openpilot/panda/board/obj/panda/main.bin"


def source_ic_table() -> bytes:
    """Les PREAP_IC_CACHE_ADDRS ut av kilden og pakk som .rodata-bytes."""
    text = TESLA_PREAP.read_text()
    m = re.search(r"PREAP_IC_CACHE_ADDRS\[[^\]]*\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        sys.exit("FEIL: fant ikke PREAP_IC_CACHE_ADDRS i tesla_preap.h — "
                 "oppdater markør-logikken hvis tabellen er fjernet med vilje.")
    addrs = [int(a, 16) for a in re.findall(r"0x[0-9A-Fa-f]+", m.group(1))]
    if len(addrs) < 4:
        sys.exit(f"FEIL: urimelig kort adressetabell i kilden: {addrs}")
    return struct.pack(f"<{len(addrs)}H", *addrs), addrs


def embedded_version(blob: bytes) -> str:
    m = re.search(rb"(DEV|RELEASE)-[0-9a-f]{8}-?(DEBUG)?", blob)
    return m.group(0).decode() if m else "(ingen versjonsstreng)"


def check_blob(name: str, blob: bytes, table: bytes, addrs: list) -> bool:
    sha = hashlib.sha256(blob).hexdigest()[:16]
    ver = embedded_version(blob)
    ok = blob.find(table) >= 0
    verdict = "OK: bygget fra dagens kilde (IC-tabell funnet)" if ok else \
              "STALE: IC-adressetabellen fra kilden finnes IKKE i binæren"
    print(f"{name}\n  sha256[:16]={sha}  versjon={ver}  størrelse={len(blob)}")
    print(f"  markør: {len(addrs)} adresser {['0x%X' % a for a in addrs[:3]]}…  → {verdict}")
    return ok


def ssh_read(host: str, path: str) -> bytes | None:
    r = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
                        host, f"cat {path}"], capture_output=True)
    return r.stdout if r.returncode == 0 and r.stdout else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--binary", type=Path, help="sjekk denne binæren i stedet")
    ap.add_argument("--c3", metavar="USER@HOST",
                    help="sjekk C3 on-disk artefakter via read-only ssh")
    args = ap.parse_args()

    table, addrs = source_ic_table()
    all_ok = True

    if args.binary:
        all_ok &= check_blob(str(args.binary), args.binary.read_bytes(), table, addrs)
    elif args.c3:
        fw = ssh_read(args.c3, C3_FW)
        if fw is None:
            print(f"FEIL: fikk ikke lest {C3_FW} fra {args.c3}"); return 2
        all_ok &= check_blob(f"{args.c3}:{C3_FW} (det pandad flasher/verifiserer)",
                             fw, table, addrs)
        main_bin = ssh_read(args.c3, C3_MAIN)
        if main_bin is not None:
            # informativt: siste kompilerte (usignerte) binær på device
            check_blob(f"{args.c3}:{C3_MAIN} (siste kompilerte, usignert — informativt)",
                       main_bin, table, addrs)
        local = COMMITTED_FW.read_bytes() if COMMITTED_FW.exists() else None
        if local is not None:
            same = hashlib.sha256(local).digest() == hashlib.sha256(fw).digest()
            print(f"  committet == C3 on-disk: {same}")
    else:
        if not COMMITTED_FW.exists():
            print(f"FEIL: {COMMITTED_FW} finnes ikke"); return 2
        all_ok &= check_blob(f"{COMMITTED_FW} (committet i nap-c3-panda)",
                             COMMITTED_FW.read_bytes(), table, addrs)

    print("\nRESULTAT:", "OK" if all_ok else
          "DRIFT — binær og kilde er ikke samme generasjon. IKKE feilsøk "
          "CAN-adferd mot denne kilden før binæren er gjenbygd+flashet.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
