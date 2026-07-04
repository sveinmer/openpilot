import subprocess, sys

REMOTE_PY = r'''
import socket, struct, select, time
from collections import defaultdict

DUR = 8
s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
s.bind(("eth0", 0)); s.setblocking(False)

# (arb) -> set of (srcmac, srcip, sport, dport)
info = defaultdict(set)
t0 = time.time()
def mac(b): return ":".join("%02x"%x for x in b)
def ip(b): return ".".join(str(x) for x in b)

end = t0+DUR
while time.time()<end:
    r,_,_ = select.select([s],[],[],0.2)
    if not r: continue
    try:
        while True:
            pkt = s.recv(2048)
            if len(pkt) < 42: continue
            if struct.unpack("!H", pkt[12:14])[0] != 0x0800: continue
            ihl = (pkt[14]&0x0F)*4
            if pkt[23] != 17: continue
            smac = mac(pkt[6:12]); dmac = mac(pkt[0:6])
            sip = ip(pkt[26:30]); dip = ip(pkt[30:34])
            uo = 14+ihl
            sport = struct.unpack("!H", pkt[uo:uo+2])[0]
            dport = struct.unpack("!H", pkt[uo+2:uo+4])[0]
            ulen = struct.unpack("!H", pkt[uo+4:uo+6])[0]
            payload = pkt[uo+8:uo+ulen]
            if len(payload) < 4: continue
            arb = struct.unpack(">H", payload[2:4])[0]
            if arb not in (0x239, 0x659): continue
            info[arb].add((smac, sip, dip, sport, dport))
    except BlockingIOError: pass

for arb in sorted(info):
    print("arb=0x%03X:" % arb)
    for smac,sip,dip,sport,dport in sorted(info[arb]):
        print("   src %s (%s:%d) -> %s:%d" % (smac, sip, sport, dip, dport))
'''

remote_cmd = ("cat > /tmp/sc.py <<'PYEOF'\n" + REMOTE_PY + "\nPYEOF\n"
              "echo pi | sudo -S python3 /tmp/sc.py; rm -f /tmp/sc.py; echo '--- ARP ---'; arp -an 2>/dev/null; echo '--- IPs ---'; hostname -I")
proc = subprocess.run(["python3","/tmp/buddy_ssh.py",remote_cmd],
                      capture_output=True, text=True, timeout=40)
print(proc.stdout)
if "arb=" not in proc.stdout:
    print("STDERR:", proc.stderr[-800:], file=sys.stderr)
