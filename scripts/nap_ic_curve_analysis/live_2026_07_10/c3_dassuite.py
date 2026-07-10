import sys,time
sys.path.append("/data/openpilot")
import cereal.messaging as messaging
DAS=[0x239,0x309,0x329,0x349,0x369,0x389,0x399,0x3A9,0x3E9,0x659,0x2B9]
sm=messaging.sub_sock("can",timeout=100)
seen={a:{} for a in DAS};t0=time.time()
while time.time()-t0<6:
    for m in messaging.drain_sock(sm):
        for c in m.can:
            if c.address in DAS and c.src==128:
                h=bytes(c.dat).hex();seen[c.address][h]=seen[c.address].get(h,0)+1
    time.sleep(0.005)
for a in DAS:
    s=seen[a]
    if s:
        rr=sorted({bytes.fromhex(h)[1] for h in s})
        print("  0x%03X: uniq=%-3d range(byte1)=%s ex=%s"%(a,len(s),rr,max(s,key=s.get)))
    else:
        print("  0x%03X: (ingen paa CAN)"%a)
