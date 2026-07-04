import subprocess, sys

REMOTE_PY = r'''
import socket, struct, select, time
from collections import Counter, defaultdict

DUR = 55
IFACES = ["eth0", "eth1"]
socks = {}
for ifn in IFACES:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    s.bind((ifn, 0)); s.setblocking(False)
    socks[s.fileno()] = (ifn, s)

seen = defaultdict(set)      # (iface,arb,dport) -> payloads
cnt = Counter()
series239 = []               # (t, iface, dport, payload) deduped-consecutive
last = {}
t0 = time.time()

def parse(ifn, pkt):
    if len(pkt) < 42: return
    if struct.unpack("!H", pkt[12:14])[0] != 0x0800: return
    ihl = (pkt[14]&0x0F)*4
    if pkt[23] != 17: return
    uo = 14+ihl
    dport = struct.unpack("!H", pkt[uo+2:uo+4])[0]
    ulen = struct.unpack("!H", pkt[uo+4:uo+6])[0]
    payload = pkt[uo+8:uo+ulen]
    if len(payload) < 4: return
    arb = struct.unpack(">H", payload[2:4])[0]
    if arb not in (0x239, 0x659): return
    data = payload[4:].hex()
    key = (ifn, arb, dport)
    seen[key].add(data); cnt[key]+=1
    if arb==0x239 and ifn=="eth0" and dport==20101:
        if last.get(key)!=data:
            series239.append((round(time.time()-t0,1), data)); last[key]=data

poller = select.poll()
for fd in socks: poller.register(fd, select.POLLIN)
end = t0+DUR
while time.time()<end:
    for fd,_ in poller.poll(200):
        ifn,s = socks[fd]
        try:
            while True: parse(ifn, s.recv(2048))
        except BlockingIOError: pass

print("=== 0x239 / 0x659 per (iface,arb,dport) ===")
for key in sorted(seen):
    ifn,arb,dport = key
    ps = list(seen[key])
    print("%-4s arb=0x%03X dport=%-5d count=%-4d uniq=%-3d  first=%s" % (
        ifn, arb, dport, cnt[key], len(ps), ps[0]))
print()
print("=== eth0:20101 0x239 endringer (kilde inn til Buddy) ===")
print("antall unike konsekutive:", len(series239))
for t,d in series239[:40]:
    print("  t=%5.1f  %s" % (t, d))
'''

remote_cmd = ("cat > /tmp/oc.py <<'PYEOF'\n" + REMOTE_PY + "\nPYEOF\n"
              "echo pi | sudo -S python3 /tmp/oc.py; rm -f /tmp/oc.py")
proc = subprocess.run(["python3","/tmp/buddy_ssh.py",remote_cmd],
                      capture_output=True, text=True, timeout=90)
print(proc.stdout)
if "per (iface" not in proc.stdout:
    print("STDERR:", proc.stderr[-800:], file=sys.stderr)
