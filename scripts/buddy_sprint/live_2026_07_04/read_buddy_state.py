import subprocess, sys

REMOTE_PY = r'''
import struct, glob

# finn tinklaBuddy pid
pid = None
for p in glob.glob("/proc/[0-9]*/comm"):
    try:
        if open(p).read().strip() == "tinklaBuddy":
            pid = p.split("/")[2]; break
    except: pass
if not pid:
    print("INGEN tinklaBuddy pid"); raise SystemExit

STATE = 0x4d5af0
def rd(addr, n):
    with open("/proc/%s/mem" % pid, "rb") as m:
        m.seek(addr); return m.read(n)

blob = rd(STATE, 0x160)
def w(off): return struct.unpack("<i", blob[off:off+4])[0]

print("pid", pid)
print("state[0x10]  (DI emit-gate)        =", w(0x10))
print("state[0x18]  (fake_das seen latch) =", w(0x18))
print("state[0x1c]                         =", w(0x1c))
print("state[0x24]  (alt emit-gate)        =", w(0x24))
print("state[0x3c]  (should_forward)       =", w(0x3c))
print("state[0x11c] DAS_fakeDasReceived    =", w(0x11c), "  <== LATCH")
print("state[0x124] (0x659 data byte4)     =", w(0x124))
print("state[0x128]                         =", w(0x128))
print("state[0x12c]                         =", w(0x12c))
print("state[0x130]                         =", w(0x130))
print("state[0x134]                         =", w(0x134))
print("state[0x138]                         =", w(0x138))
print("state[0x144]                         =", w(0x144))
'''

remote_cmd = ("cat > /tmp/rm.py <<'PYEOF'\n" + REMOTE_PY + "\nPYEOF\n"
              "echo pi | sudo -S python3 /tmp/rm.py; rm -f /tmp/rm.py")
proc = subprocess.run(["python3","/tmp/buddy_ssh.py",remote_cmd],
                      capture_output=True, text=True, timeout=40)
print(proc.stdout)
if proc.returncode != 0 or "LATCH" not in proc.stdout:
    print("STDERR:", proc.stderr[-800:], file=sys.stderr)
