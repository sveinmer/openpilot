# Buddy live-verktøy (2026-07-04 kveld) — brukt til å frikjenne Buddy for 0x239

Verktøyene som beviste at 0x239 ankommer Buddy allerede-konstant fra `gw`
(192.168.90.102), ikke genereres av Buddy. Se
`docs/NAP_HANDOVER_2026_07_04_KVELD_0x239_UPSTREAM_GW.md`.

**Forutsetning:** dev-boks på Buddy-WiFi `tinklaAP` (Buddy @ 10.5.5.1, pi@ + BUDDY_PASS).
Buddy har IKKE tcpdump/base64 → alt bruker AF_PACKET-Python via `sudo`.
Alle scripts kaller `buddy_ssh.py` (ligger i samme mappe — kopier begge til
`/tmp/` eller kjør fra denne mappen; scriptene peker på `/tmp/buddy_ssh.py`,
juster stien ved behov).

| Script | Hva det gjør |
|---|---|
| `buddy_ssh.py` | pexpect SSH-wrapper, kommando som SSH-arg, streamer til EOF |
| `buddy_scp.py` | pexpect scp-wrapper — hentet `tinklaBuddy.v149` |
| `read_buddy_state.py` | Leser tinklaBuddy state-globals LIVE via /proc/PID/mem (DAS_fakeDasReceived m.fl.). Binær er ET_EXEC → faste adresser (state-base 0x4d5af0). |
| `identify_source.py` | src MAC/IP per arb-id på eth0 — fant `gw` som kilde |
| `onroad_0x239_source.py` | per-(iface,arb,dport) capture + 0x239 tidsserie (kjør mens bil kjører) |
| `perport_capture.py` | kort per-port 0x239/0x659-snapshot (parkert ok) |

## Nøkkelfunn (alle live-målt)
- `DAS_fakeDasReceived` (0x4d5c0c) = **1** — latch satt, Buddy tar ekte-grenen.
- 0x239 på eth0:20101 = konstant `1001030b80011212` (uniq=1) også onroad.
- 0x659 på eth0:20101 = varierer (uniq=404). Begge fra `gw` 192.168.90.102.
- => Buddy videresender; kilden `gw` sender konstant 0x239. Fix oppstrøms (C3).
