#!/usr/bin/env python3
"""T4 — Parallell capture eth0+eth1 på Buddy med AF_PACKET (ingen tcpdump/base64).

Kjørt og verifisert 2026-07-04. Bruker custom AF_PACKET sniffer fordi
Buddy (Ubuntu 20.04 aarch64) ikke har tcpdump eller base64 installert.

Krav: /tmp/buddy_ssh.py (pexpect-wrapper, pi/pi @ 10.5.5.1)
      Bil kjørende (IsOnroad=1) for at openpilot sender DAS-frames

Bruk: python3 t4_dual_capture_afpacket.py [duration_sek]
"""
import subprocess, sys, json

DURATION = int(sys.argv[1]) if len(sys.argv) > 1 else 45

REMOTE_PY = r'''
import socket, struct, select, time, json
from collections import Counter

DUR = __DUR__
IFACES = ["eth0", "eth1"]
PORTS = {20101, 20201, 31415, 31515}
DAS = {0x239:"DAS_lanes",0x309:"DAS_object",0x329:"warnMx0",0x369:"warnMx1",0x349:"warnMx3",
       0x389:"DAS_status2",0x399:"DAS_status",0x3A9:"telemetry",0x3E9:"bodyControls",
       0x659:"DAS_fake",0x2B9:"DAS_control"}

socks = {}
for ifn in IFACES:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    s.bind((ifn, 0)); s.setblocking(False)
    socks[s.fileno()] = (ifn, s)

arbs = {i: Counter() for i in IFACES}
payloads = {i: {} for i in IFACES}
lane_series = []
t0 = time.time()
last239 = None

def decode239(hexstr):
    v = int.from_bytes(bytes.fromhex(hexstr), "little")
    g = lambda s,l: (v>>s)&((1<<l)-1)
    return {"lExist":g(0,1),"rExist":g(1,1),"width":round(g(4,4)*0.3125+2,2),
            "range":g(8,8),"C0":round(g(16,8)*0.035-3.5,3),"C1":round(g(24,8)*0.0016-0.2,4),
            "C2":round(g(32,8)*2e-5-0.0025,6),"C3":round(g(40,8)*2.4e-7-3e-5,8),"cnt":g(60,4)}

def parse(ifn, pkt):
    global last239
    if len(pkt) < 42: return
    if struct.unpack("!H", pkt[12:14])[0] != 0x0800: return
    ihl = (pkt[14]&0x0F)*4
    if pkt[23] != 17: return
    uo = 14+ihl
    dport = struct.unpack("!H", pkt[uo+2:uo+4])[0]
    sport = struct.unpack("!H", pkt[uo:uo+2])[0]
    if dport not in PORTS and sport not in PORTS: return
    ulen = struct.unpack("!H", pkt[uo+4:uo+6])[0]
    payload = pkt[uo+8:uo+ulen]
    if len(payload) < 4: return
    arb = struct.unpack(">H", payload[2:4])[0]
    data = payload[4:].hex()
    arbs[ifn][arb]+=1
    payloads[ifn].setdefault(arb,set()).add(data)
    if ifn=="eth0" and arb==0x239 and data!=last239:
        lane_series.append((round(time.time()-t0,2), data)); last239=data

poller = select.poll()
for fd in socks: poller.register(fd, select.POLLIN)
end = t0+DUR
while time.time()<end:
    for fd,_ in poller.poll(200):
        ifn,s = socks[fd]
        try:
            while True: parse(ifn, s.recv(2048))
        except BlockingIOError: pass

out={"dur":DUR,"ifaces":{}}
for ifn in IFACES:
    das={}
    for a,name in DAS.items():
        if a in arbs[ifn]:
            das["0x%03X"%a]={"name":name,"count":arbs[ifn][a],"uniq":len(payloads[ifn].get(a,()))}
    out["ifaces"][ifn]={"total":sum(arbs[ifn].values()),"arbs":len(arbs[ifn]),"das":das}
out["lane_changes_eth0"]=len(lane_series)
out["lane_series"]=[(t,h,decode239(h)) for t,h in lane_series[:60]]
print("===CAPJSON===")
print(json.dumps(out))
print("===CAPEND===")
'''.replace("__DUR__", str(DURATION))

remote_cmd = ("cat > /tmp/cap.py <<'PYEOF'\n"+REMOTE_PY+"\nPYEOF\n"
              "echo pi | sudo -S python3 /tmp/cap.py; rm -f /tmp/cap.py")
proc = subprocess.run(["python3","/tmp/buddy_ssh.py",remote_cmd],
                      capture_output=True, text=True, timeout=DURATION+40)
out = proc.stdout
b,e = out.find("===CAPJSON==="), out.find("===CAPEND===")
if b==-1 or e==-1:
    print("[capture] no JSON; tail:", out[-1500:], file=sys.stderr)
    print("ERR:", proc.stderr[-500:], file=sys.stderr); sys.exit(1)
result = json.loads(out[b+len("===CAPJSON==="):e].strip())
print(json.dumps(result, indent=2))
