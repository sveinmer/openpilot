#!/usr/bin/env python3
"""T5 inject-test — AF_PACKET versjon (ingen tcpdump/base64).

Kjørt og verifisert 2026-07-04. Resultat: REPLACES_WITH_CONSTANT.

Sender 10x EtherCAN 0x239-frames med payload DEADBEEF11223344 til Buddy's
127.0.0.1:20101, mens eth1 lyttes på med AF_PACKET.

Resultat-tolkning:
  FORWARDS_INJECT        -> Buddy videresender vår frame til IC
  REPLACES_WITH_CONSTANT -> Buddy har aktiv IC-generator som overrider alt
  DROPS_OR_EMPTY         -> Buddy droppet framen, ingen 0x239 på eth1

Krav: /tmp/buddy_ssh.py (pexpect-wrapper, pi/pi @ 10.5.5.1)
"""
import subprocess, sys, json

REMOTE_PY = r'''
import socket, struct, select, time, threading, json

CAPTURE_DUR = 8
INJECT_DELAY = 1.5
INJECT_COUNT = 10
INJECT_INTERVAL = 0.15
FRAME = bytes.fromhex("00000239DEADBEEF11223344")
results = {"eth1_0x239": [], "inject_sent": 0}

def sniffer():
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(0x0003))
    s.bind(("eth1", 0)); s.setblocking(False)
    seen = set()
    t0 = time.time()
    PORTS = {20101, 20201, 31415, 31515}
    while time.time() - t0 < CAPTURE_DUR:
        r, _, _ = select.select([s], [], [], 0.2)
        if not r: continue
        try:
            while True:
                pkt = s.recv(2048)
                if len(pkt) < 42: continue
                if struct.unpack("!H", pkt[12:14])[0] != 0x0800: continue
                ihl = (pkt[14] & 0x0F) * 4
                if pkt[23] != 17: continue
                uo = 14 + ihl
                dport = struct.unpack("!H", pkt[uo+2:uo+4])[0]
                sport = struct.unpack("!H", pkt[uo:uo+2])[0]
                if dport not in PORTS and sport not in PORTS: continue
                ulen = struct.unpack("!H", pkt[uo+4:uo+6])[0]
                payload = pkt[uo+8:uo+ulen]
                if len(payload) < 4: continue
                arb = struct.unpack(">H", payload[2:4])[0]
                if arb != 0x239: continue
                data = payload[4:].hex()
                if data not in seen:
                    seen.add(data)
                    results["eth1_0x239"].append({"t": round(time.time()-t0,2), "payload": data})
        except BlockingIOError:
            pass
    s.close()

def injector():
    time.sleep(INJECT_DELAY)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for i in range(INJECT_COUNT):
        sock.sendto(FRAME, ("127.0.0.1", 20101))
        results["inject_sent"] += 1
        time.sleep(INJECT_INTERVAL)
    sock.close()

t_sniff = threading.Thread(target=sniffer)
t_inject = threading.Thread(target=injector)
t_sniff.start(); t_inject.start()
t_sniff.join(); t_inject.join()

eth1_payloads = [r["payload"] for r in results["eth1_0x239"]]
has_deadbeef = any("deadbeef" in p for p in eth1_payloads)
has_constant = any("1001030b" in p for p in eth1_payloads)
results["verdict"] = (
    "FORWARDS_INJECT" if has_deadbeef else
    "REPLACES_WITH_CONSTANT" if has_constant else
    "DROPS_OR_EMPTY"
)
print("===T5JSON===")
print(json.dumps(results, indent=2))
print("===T5END===")
'''

remote_cmd = ("cat > /tmp/t5r.py <<'PYEOF'\n" + REMOTE_PY + "\nPYEOF\n"
              "echo pi | sudo -S python3 /tmp/t5r.py; rm -f /tmp/t5r.py")

proc = subprocess.run(
    ["python3", "/tmp/buddy_ssh.py", remote_cmd],
    capture_output=True, text=True, timeout=60
)
out = proc.stdout
b, e = out.find("===T5JSON==="), out.find("===T5END===")
if b == -1 or e == -1:
    print("[t5] no JSON; tail:", out[-2000:], file=sys.stderr)
    print("ERR:", proc.stderr[-500:], file=sys.stderr)
    sys.exit(1)

data = json.loads(out[b+len("===T5JSON==="):e].strip())
print(json.dumps(data, indent=2))
print()
print("=== VERDICT:", data.get("verdict"), "===")
print("Injected:", data["inject_sent"], "frames")
print("Unique 0x239 on eth1:", len(data["eth1_0x239"]))
for entry in data["eth1_0x239"]:
    p = entry["payload"]
    tag = " <-- INJECTED" if "deadbeef" in p else (" <-- BUDDY-CONSTANT" if "1001030b" in p else "")
    print("  t={}s  {}{}".format(entry["t"], p, tag))
