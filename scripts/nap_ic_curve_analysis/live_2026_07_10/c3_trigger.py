import sys,time
sys.path.append("/data/openpilot")
import cereal.messaging as messaging
sm=messaging.sub_sock("can",timeout=100)
gtw=0; ic192={}; ic128={}; t0=time.time()
ICADDR={0x239,0x309,0x329,0x349,0x369,0x389,0x399,0x3a9,0x3b1,0x3e9}
while time.time()-t0<8:
    for m in messaging.drain_sock(sm):
        for c in m.can:
            if c.address==0x348 and c.src in (0,128): gtw+=1
            if c.address in ICADDR:
                if c.src==192: ic192[c.address]=ic192.get(c.address,0)+1
                elif c.src==128: ic128[c.address]=ic128.get(c.address,0)+1
    time.sleep(0.005)
print("GTW_status 0x348 (IC-emit trigger) paa bus0: %d frames"%gtw)
print("IC-frames src=192 (panda IC-emit / fake-kanal):", {hex(k):v for k,v in ic192.items()} or "INGEN")
print("IC-frames src=128 (openpilot direkte):", {hex(k):v for k,v in ic128.items()} or "INGEN")
