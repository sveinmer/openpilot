#!/usr/bin/env python3
"""pexpect scp-wrapper for Buddy (pi/pi @ 10.5.5.1).
Usage: python3 buddy_scp.py <remote_path> <local_path>
"""
import sys, pexpect

HOST, USER, PASS = "10.5.5.1", "pi", "pi"

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
        child.sendline(PASS)
    elif i != 1:
        print("[scp] timeout på password-prompt", file=sys.stderr)
        child.close(force=True); return 1
    child.expect(pexpect.EOF, timeout=120)
    child.close()
    return child.exitstatus if child.exitstatus is not None else 0

if __name__ == "__main__":
    sys.exit(main())
