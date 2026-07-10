import sys,time
sys.path.append("/data/openpilot")
import cereal.messaging as messaging
sm=messaging.sub_sock("can",timeout=100)
# src: 0=bus0 rx, 128=bus0 tx, 1=bus1, 129=bus1 tx, 2=bus2, 130=bus2 tx
busarb=  {}   # src -> set(arb)
vis={0x239:{},0x309:{}}  # arb -> src -> count
t0=time.time()
while time.time()-t0<6:
    for m in messaging.drain_sock(sm):
        for c in m.can:
            busarb.setdefault(c.src,set()).add(c.address)
            if c.address in vis:
                vis[c.address].setdefault(c.src,0); vis[c.address][c.src]+=1
    time.sleep(0.005)
print("=== CAN busser (src -> antall arb-IDs) ===")
for s in sorted(busarb):
    lbl={0:"bus0-rx",128:"bus0-tx",1:"bus1-rx",129:"bus1-tx",2:"bus2-rx",130:"bus2-tx"}.get(s,"src%d"%s)
    print("  %-8s (src=%d): %d arb-IDs"%(lbl,s,len(busarb[s])))
print("=== 0x239 / 0x309 per src (hvilken bus) ===")
for a in (0x239,0x309):
    print("  0x%03X: %s"%(a,{("src%d"%k):v for k,v in vis[a].items()} or "INGEN"))
# er 0x239 paa bus2 (der APE sitter)?
