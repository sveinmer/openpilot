#!/usr/bin/env python3
"""C3-side live 0x239 DAS_lanes leser — for SAMTIDIG CAN-vs-ethernet-test.

Kjøres PÅ C3 (bil PÅ / onroad) SAMTIDIG med Buddy-ethernet-capturen
(`scripts/buddy_sprint/live_2026_07_04/onroad_0x239_source.py`). Målet er å
avgjøre den ene gjenstående forgreningen (se
`docs/NAP_HANDOVER_2026_07_04_KVELD_0x239_UPSTREAM_GW.md` §5 + C3-side-doc):

  CAN 0x239 = range=50, varierer   +  ethernet 0x239 = range=1, konstant
    => openpilot SENDER; GTW/gw broer ikke openpilots 0x239 → GTW-sak.

  CAN 0x239 fraværende / range≠50
    => openpilot sender ikke 0x239 (enableICIntegration=False i kjørende
       prosess, param-timing) → ren openpilot/param/reboot-fix.

Leser BÅDE `sendcan` (openpilot TX) og `can` (fysisk buss + TX-ekko src=128),
dekoder DAS_virtualLaneViewRange (byte1) og teller unike payloads.

Kjør i C3-venv:
  PYTHONPATH=/data/openpilot /usr/local/venv/bin/python c3_can_0x239.py [sek]
"""
import sys, time
sys.path.append("/data/openpilot")
import cereal.messaging as messaging

DUR = int(sys.argv[1]) if len(sys.argv) > 1 else 30
DAS_LANES = 0x239

def decode_range(dat):
    # DAS_virtualLaneViewRange = byte1 (8|8@1+), scale 1 → rå byte1
    return dat[1] if len(dat) >= 2 else None

sm_sendcan = messaging.sub_sock("sendcan", timeout=100)
sm_can = messaging.sub_sock("can", timeout=100)

seen = {"sendcan": {}, "can_src": {}}   # payloads per (kilde/src)
counts = {"sendcan": 0, "can": 0}
ranges = {"sendcan": set(), "can": set()}

t0 = time.time()
print("Lytter %ds på 0x239 (sendcan + can)…  (bil må være ONROAD)" % DUR)
while time.time() - t0 < DUR:
    for msg in messaging.drain_sock(sm_sendcan):
        for c in msg.sendcan:
            if c.address == DAS_LANES:
                counts["sendcan"] += 1
                h = bytes(c.dat).hex()
                seen["sendcan"].setdefault(h, 0)
                seen["sendcan"][h] += 1
                r = decode_range(bytes(c.dat))
                if r is not None: ranges["sendcan"].add(r)
    for msg in messaging.drain_sock(sm_can):
        for c in msg.can:
            if c.address == DAS_LANES:
                counts["can"] += 1
                key = "src%d" % c.src
                h = bytes(c.dat).hex()
                seen["can_src"].setdefault(key, {}).setdefault(h, 0)
                seen["can_src"][key][h] += 1
                r = decode_range(bytes(c.dat))
                if r is not None: ranges["can"].add(r)
    time.sleep(0.01)

print("\n=== sendcan (openpilot TX) 0x239 ===")
print("count=%d uniq=%d ranges=%s" % (counts["sendcan"], len(seen["sendcan"]),
      sorted(ranges["sendcan"])))
for h, n in sorted(seen["sendcan"].items(), key=lambda x: -x[1])[:5]:
    print("   %-16s x%d  range=%d" % (h, n, bytes.fromhex(h)[1]))

print("\n=== can (fysisk buss + TX-ekko) 0x239 per src ===")
print("count=%d ranges=%s" % (counts["can"], sorted(ranges["can"])))
for src, payloads in seen["can_src"].items():
    print(" %s: uniq=%d" % (src, len(payloads)))
    for h, n in sorted(payloads.items(), key=lambda x: -x[1])[:4]:
        print("   %-16s x%d  range=%d" % (h, n, bytes.fromhex(h)[1]))

print("\n=== TOLKNING ===")
if counts["sendcan"] == 0 and counts["can"] == 0:
    print("INGEN 0x239 — bil offroad, eller openpilot sender IKKE 0x239")
    print("=> sjekk enableICIntegration / NAPTinklaICIntegration i kjørende prosess")
elif ranges["sendcan"] and 50 in ranges["sendcan"]:
    print("openpilot SENDER range=50 på CAN. Hvis Buddy-ethernet samtidig = range=1")
    print("=> GTW/gw broer ikke openpilots 0x239 (Tesla-GTW-sak), ikke openpilot.")
else:
    print("openpilot 0x239 range != 50 eller uventet — undersøk enableICIntegration.")
