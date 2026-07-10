import sys
sys.path.append("/data/openpilot")
from cereal import log as capnp_log
with open(sys.argv[1],'rb') as f: buf=f.read()
from collections import defaultdict
srcarb=defaultdict(set)
for msg in capnp_log.Event.read_multiple_bytes(buf):
    if msg.which()=="can":
        for c in msg.can:
            srcarb[c.src].add(c.address)
for s in sorted(srcarb):
    das=[hex(a) for a in sorted(srcarb[s]) if 0x200<=a<=0x700]
    print("  src=%-4d : %d arb totalt, DAS: %s"%(s,len(srcarb[s]),das[:12]))
