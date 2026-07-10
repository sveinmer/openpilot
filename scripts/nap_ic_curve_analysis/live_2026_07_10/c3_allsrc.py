import sys,time
sys.path.append("/data/openpilot")
import cereal.messaging as messaging
sm=messaging.sub_sock("can",timeout=100)
per={};t0=time.time()
while time.time()-t0<7:
    for m in messaging.drain_sock(sm):
        for c in m.can:
            if c.address==0x239:
                per.setdefault(c.src,{});h=bytes(c.dat).hex();per[c.src][h]=per[c.src].get(h,0)+1
    time.sleep(0.005)
print("=== 0x239 ALLE src/busser paa CAN ===")
for s in sorted(per):
    ps=per[s];rr=sorted({bytes.fromhex(h)[1] for h in ps})
    print("  src=%-4d uniq=%-3d range=%s ex=%s"%(s,len(ps),rr,max(ps,key=ps.get)))
if not per: print("  ingen 0x239")
