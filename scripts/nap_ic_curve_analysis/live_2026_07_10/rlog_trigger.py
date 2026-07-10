import sys
sys.path.append("/data/openpilot")
from cereal import log as capnp_log
with open(sys.argv[1],'rb') as f: buf=f.read()
gtw=0; s192=set(); s128=set()
ICADDR={0x239,0x309,0x329,0x349,0x369,0x389,0x399,0x3a9,0x3b1,0x3e9}
for msg in capnp_log.Event.read_multiple_bytes(buf):
    if msg.which()=="can":
        for c in msg.can:
            if c.address==0x348 and c.src in (0,128): gtw+=1
            if c.address in ICADDR:
                if c.src==192: s192.add(c.address)
                elif c.src==128: s128.add(c.address)
print("  0x348 trigger: %d | src=192 IC-frames: %s"%(gtw,sorted(hex(a) for a in s192)))
