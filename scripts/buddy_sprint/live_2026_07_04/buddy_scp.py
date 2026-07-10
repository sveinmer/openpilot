#!/usr/bin/env python3
"""pexpect scp-wrapper for Buddy (bruker pi @ 10.5.5.1).
Passord: env BUDDY_PASS eller ~/.config/nap/buddy_pass (aldri hardkodet — public repo).
Usage: python3 buddy_scp.py <remote_path> <local_path>
"""
import os, sys, pexpect
from pathlib import Path

HOST, USER = "10.5.5.1", "pi"


def buddy_pass() -> str:
    pw = os.environ.get("BUDDY_PASS")
    if pw:
        return pw
    f = Path.home() / ".config/nap/buddy_pass"
    if f.exists():
        return f.read_text().strip()
    sys.exit("[scp] sett BUDDY_PASS eller legg passordet i ~/.config/nap/buddy_pass")

def main():
    remote, local = sys.argv[1], sys.argv[2]
    opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "PubkeyAuthentication=no",
        "-o", "LogLevel=ERROR",
        f"{USER}@{HOST}:{remote}",
        local,
    ]
    child = pexpect.spawn("scp", args=opts, encoding="utf-8", timeout=120)
    i = child.expect(["[Pp]assword:", pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(buddy_pass())
    elif i != 1:
        print("[scp] timeout på password-prompt", file=sys.stderr)
        child.close(force=True); return 1
    child.expect(pexpect.EOF, timeout=120)
    child.close()
    return child.exitstatus if child.exitstatus is not None else 0

if __name__ == "__main__":
    sys.exit(main())
