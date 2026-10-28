#!/usr/bin/env python3
"""kmsgd: persist the kernel log (dmesg -w) to /data/kmsg/.

On AGNOS the systemd journal lives in RAM and pstore is empty after a cold
boot, so kernel messages from a storage failure are lost by the time the
device is power cycled. This daemon tails dmesg and writes it to flash,
fsyncing lines that look like storage or driver errors.
"""
import datetime
import os
import subprocess
import time

from openpilot.common.swaglog import cloudlog

KMSG_DIR = "/data/kmsg"
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_FILES = 40
SYNC_KEYWORDS = ("ufs", "UFS", "EXT4", "I/O error", "error", "Error", "fail",
                 "abort", "timeout", "scsi", "sd 0:", "reset", "remount", "Oops", "BUG")


def _cleanup() -> None:
  # Sort by mtime, not by name: the file name carries the boot-time clock, which is
  # wrong (2025-07-02) until NTP/GPS sync, so name order is not chronological.
  files = sorted((f for f in os.listdir(KMSG_DIR) if f.startswith("kmsg-")),
                 key=lambda f: os.path.getmtime(os.path.join(KMSG_DIR, f)))
  for f in files[:-MAX_FILES]:
    try:
      os.remove(os.path.join(KMSG_DIR, f))
    except OSError:
      pass


def _open():
  _cleanup()
  name = datetime.datetime.now().strftime("kmsg-%Y%m%d-%H%M%S") + f"-{os.getpid()}.log"
  return open(os.path.join(KMSG_DIR, name), "a", buffering=1)


def main() -> None:
  os.makedirs(KMSG_DIR, exist_ok=True)
  while True:
    f = None
    proc = None
    try:
      f = _open()
      proc = subprocess.Popen(["dmesg", "-w"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, errors="replace")
      assert proc.stdout is not None
      for line in proc.stdout:
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{now} {line}")
        if any(k in line for k in SYNC_KEYWORDS):
          try:
            os.fsync(f.fileno())
          except OSError:
            pass
        if f.tell() > MAX_FILE_BYTES:
          f.close()
          f = _open()
      cloudlog.warning("kmsgd: dmesg -w exited, restarting")
    except Exception:
      cloudlog.exception("kmsgd failed")
    finally:
      if proc is not None:
        proc.kill()
        proc.wait()
      if f is not None:
        try:
          f.close()
        except OSError:
          pass
    time.sleep(5)


if __name__ == "__main__":
  main()
