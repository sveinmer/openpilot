#!/usr/bin/env python3
"""Robust pexpect SSH-wrapper for Tinkla Buddy (pi/pi @ 10.5.5.1).

Passes the remote command as a single ssh argument (no interactive shell /
prompt-matching), answers the password once, then streams remote stdout to
our stdout until EOF. Exit status mirrors ssh's.

Usage: python3 /tmp/buddy_ssh.py "<remote command>"
"""
import sys
import pexpect

HOST = "10.5.5.1"
USER = "pi"
PASS = "pi"

def main():
    if len(sys.argv) < 2:
        print("usage: buddy_ssh.py '<remote command>'", file=sys.stderr)
        return 2
    remote_cmd = sys.argv[1]
    ssh_opts = [
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=8",
        "-o", "PubkeyAuthentication=no",
        "-o", "LogLevel=ERROR",
        "-tt",                       # force PTY so sudo -S / password work
        f"{USER}@{HOST}",
        remote_cmd,
    ]
    child = pexpect.spawn("ssh", args=ssh_opts, encoding="utf-8", timeout=180)
    # First interaction: the login password prompt.
    i = child.expect(["[Pp]assword:", pexpect.EOF, pexpect.TIMEOUT])
    if i == 0:
        child.sendline(PASS)
    elif i != 1:
        print("\n[buddy_ssh] timeout waiting for password prompt", file=sys.stderr)
        child.close(force=True)
        return 1
    # Stream everything else to stdout until the session ends.
    child.logfile_read = sys.stdout
    child.expect(pexpect.EOF, timeout=None)
    child.close()
    return child.exitstatus if child.exitstatus is not None else 0

if __name__ == "__main__":
    sys.exit(main())
