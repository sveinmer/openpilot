import sys
sys.path.append("/data/openpilot")
import capnp
from cereal import log as capnp_log
path=sys.argv[1]
if path.endswith(".zst"):
    import zstandard
    with open(path,'rb') as f:
        buf=zstandard.ZstdDecompressor().stream_reader(f).read()
else:
    with open(path,'rb') as f: buf=f.read()
per={}
for msg in capnp_log.Event.read_multiple_bytes(buf):
    w=msg.which()
    if w=="can":
        for c in msg.can:
            if c.address==0x239:
                per.setdefault(c.src,{});h=bytes(c.dat).hex();per[c.src][h]=per[c.src].get(h,0)+1
    elif w=="sendcan":
        for c in msg.sendcan:
            if c.address==0x239:
                k="SEND%d"%c.src
                per.setdefault(k,{});h=bytes(c.dat).hex();per[k][h]=per[k].get(h,0)+1
print("=== 0x239 per src i %s ==="%path.split('/')[-2])
for s in sorted(per,key=str):
    ps=per[s];rr=sorted({bytes.fromhex(h)[1] for h in ps})
    print("  src=%-8s uniq=%-3d range=%s ex=%s"%(str(s),len(ps),rr,max(ps,key=ps.get)))
if not per:print("  ingen 0x239 (kurver via annen mekanisme?)")
