#!/usr/bin/env python3
"""C3-side 0x239 DAS_lanes — TELL KILDER (src) på CAN. Live ELLER offline rlog.

Kjernespørsmål (Sveins prinsipp «bilen endret seg ikke»): comma-side sender
beviselig 0x239 range=50 (alle gates åpne — søster-DAS-frames lever på ethernet),
men ethernet viser range=1. Eneste måte å bryte selvmotsigelsen:

  HVOR MANGE 0x239-KILDER er på CAN, og hva er deres range?
  - Kun src=128 (openpilot TX-echo), range=50  → comma sender; noe nedstrøms
    (bil/gw) overstyrer i IC-sloten. Se om ethernet-siden samtidig = range=1.
  - EN EKSTRA src med range=1  → bilens egen native idle-DAS_lanes ligger på
    bussen ved siden av vår. DEN er synderen (ikke openpilot). Sjekk om den
    dukket opp etter bil-byttet (diff mot før-switch rlog).

Bilen er PreAP → carFingerprint gate (should_send) alltid True, så 0x239 SKAL
sendes. Dette scriptet avgjør om den faktisk er der, og om den er alene.

BRUK:
  Live (bil på/onroad):
    PYTHONPATH=/data/openpilot /usr/local/venv/bin/python c3_can_0x239.py [sek]
  Offline (fersk rlog, INGEN kjøring nødvendig):
    PYTHONPATH=/data/openpilot /usr/local/venv/bin/python c3_can_0x239.py \
        --rlog /data/media/0/realdata/<rute>/rlog
"""
import sys, time

sys.path.append("/data/openpilot")
DAS_LANES = 0x239

def rng(dat):
    return dat[1] if len(dat) >= 2 else -1

def report(per_src):
    print("\n=== 0x239 kilder på CAN (per src) ===")
    if not per_src:
        print("  INGEN 0x239 på CAN — openpilot sender ikke (sjekk enableICIntegration/"
              "preap_has_ic_integration i kjørende stack), ELLER bil offroad.")
        return
    for src in sorted(per_src):
        payloads = per_src[src]
        ranges = sorted({rng(bytes.fromhex(h)) for h in payloads})
        top = sorted(payloads.items(), key=lambda x: -x[1])[:3]
        print("  src=%-4d  uniq=%-3d  ranges=%s" % (src, len(payloads), ranges))
        for h, n in top:
            print("      %-16s x%-4d range=%d" % (h, n, bytes.fromhex(h)[1]))
    print("\n--- TOLKNING ---")
    src_ranges = {src: sorted({rng(bytes.fromhex(h)) for h in p}) for src, p in per_src.items()}
    has_50 = any(50 in r for r in src_ranges.values())
    has_1  = any(1 in r for r in src_ranges.values())
    if has_50 and has_1:
        print("  TO signaturer: range=50 (openpilot) OG range=1 (bilens native idle).")
        print("  => Bilens egen DAS_lanes ligger på bussen. Synderen er IKKE openpilot.")
        print("     Diff mot før-switch rlog: dukket range=1-kilden opp etter bil-byttet?")
    elif has_50 and not has_1:
        print("  KUN range=50 (openpilot). 0x239 er frisk på CAN, alene.")
        print("  => Overstyringen til range=1 skjer NEDSTRØMS (gw/bil-bro). Mål ethernet")
        print("     samtidig (Buddy onroad_0x239_source.py) for å bekrefte divergensen.")
    elif has_1 and not has_50:
        print("  KUN range=1 og INGEN range=50 → openpilot sender ikke sin egen 0x239.")
        print("  => comma-side gate lukket i praksis tross param. Finn hvilken.")
    else:
        print("  Uventede ranges — inspiser payloads over.")

def run_live(dur):
    import cereal.messaging as messaging
    sm = messaging.sub_sock("can", timeout=100)
    per_src = {}
    print("Lytter %ds på 'can' for 0x239 (bil bør være onroad)…" % dur)
    t0 = time.time()
    while time.time() - t0 < dur:
        for msg in messaging.drain_sock(sm):
            for c in msg.can:
                if c.address == DAS_LANES:
                    per_src.setdefault(c.src, {})
                    h = bytes(c.dat).hex()
                    per_src[c.src][h] = per_src[c.src].get(h, 0) + 1
        time.sleep(0.01)
    report(per_src)

def run_offline(path):
    from openpilot.tools.lib.logreader import LogReader
    per_src = {}
    print("Leser rlog offline: %s" % path)
    for msg in LogReader(path):
        if msg.which() == "can":
            for c in msg.can:
                if c.address == DAS_LANES:
                    per_src.setdefault(c.src, {})
                    h = bytes(c.dat).hex()
                    per_src[c.src][h] = per_src[c.src].get(h, 0) + 1
    report(per_src)

if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--rlog":
        run_offline(sys.argv[2])
    else:
        run_live(int(sys.argv[1]) if len(sys.argv) > 1 else 30)
