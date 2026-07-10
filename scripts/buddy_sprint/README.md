# Buddy live-sprint scripts (2026-05-25, kjørt 2026-07-04)

## RESULTAT — se `docs/NAP_BUDDY_0x239_FINDINGS_2026_07_04.md`

Root cause bekreftet: Buddy MITM-erstatter openpilot's 0x239 med konstant
`1001030b00011212`. Fix er på Buddy-siden (tinklaBuddy binary-logikk).

T4 (AF_PACKET-versjon) og T5 (AF_PACKET-versjon) ble kjørt og verifisert 2026-07-04.
Se `t4_dual_capture_afpacket.py` og `t5_inject_afpacket.py` — tilpasset fordi
Buddy IKKE har tcpdump eller base64 installert.

---

# Buddy live-sprint pre-flighted scripts (2026-05-25)

**Mål:** Identifiser kilden til konstant `7001030b80101611` på Buddy eth1 0x239
DAS_lanes via 5 evidens-genererende tester. Hver test eliminerer minst én hypotese.

**Filosofi:** TEMP-only på Buddy (per `.claude/memory/feedback_buddy_temp_only.md`).
Trap-atomic, reversibel, idempotent.

## Pre-conditions

- Bilen tilkoblet Buddy WiFi (10.5.5.x SSID `tinklaAP`)
- c3 booted (slik at panda emitterer 0x239 — vi observerer dette nedstrøms)
- Sveins er parkert med bil på (controlsd-aktiv state)
- Dev-box har Wi-Fi-tilkobling til samme nett som Buddy (10.5.5.1/24)
- Buddy-creds (pi@ + BUDDY_PASS/lokal memory) (eksisterende `/tmp/buddy_ssh.py`-wrapper)

## Skript-oversikt

| Skript | Test | Tid | Hva det beviser |
|---|---|---|---|
| `t2_inventory.sh` | Buddy live-state | <1 min | Hvilke prosesser/sockets/forbindelser kjører |
| `t3_arp_mac.sh` | MAC-eier-identifikasjon | ~2 min | Hvem eier `0000a7010203` |
| `t1_sigstop.sh` | SIGSTOP tinklaBuddy + capture | ~30s | Om tinklaBuddy ER kilden |
| `t4_dual_capture.py` | Parallell eth0 + eth1 capture | 30s | Forward vs generate vs filter |
| `t5_inject_test.py` | Send fake 0x239 til port 20101 | <30s | Buddy's behandling av nye 0x239-frames |
| `t6_0x399_vs_0x239.py` | Dev-box analyse av T4-output | ~10s | Hvorfor 0x399 passerer men 0x239 ikke |
| `t7_web_ui.sh` | curl Buddy web-UI | <10s | Buddy config/status |
| `run_all.sh` | Orchestrator | ~5 min | Kjør T1-T7 sekvensielt, samle output |

## Output-struktur

Alle skript skriver til `/tmp/buddy_sprint_<timestamp>/` på dev-box:

```
/tmp/buddy_sprint_20260525_xxxxxx/
├── README.md                  # auto-genrert summary
├── t1_sigstop_capture.json    # capture mens tinklaBuddy stopper
├── t2_inventory/
│   ├── ps_auxf.txt
│   ├── netstat_anup.txt
│   ├── lsof_udp.txt
│   ├── ip_a.txt
│   ├── arp_an.txt
│   └── proc_fd.txt
├── t3_arp_mac.txt
├── t4_dual_capture/
│   ├── eth0.pcap
│   ├── eth1.pcap
│   └── summary.json
├── t5_inject.json
├── t6_analysis.txt
└── t7_web_ui/
    ├── root.html
    ├── status.html
    └── config.html
```

## Kjøre-rekkefølge (beslutningstre)

T2 → T3 → T1 → T4 → T5 → T6 → T7. T6 er post-analyse av T4.

Hvis T3 viser MAC = Buddy's egen eth1 → fortsett T1 for å bevise kilden.
Hvis T1 viser 0x239 stopper når tinklaBuddy stopper → kilden er bevist.
Hvis T1 viser 0x239 fortsetter → kilden er ekstern (Tesla IC-bus-side).
T4 gir alltid forward/generate-distinksjon uansett.
T5 viser hvordan Buddy behandler vår sandbox-frame.

## Sikkerhet

- T1 sender SIGSTOP til tinklaBuddy. Trap-atomic SIGCONT på exit/int/term.
  Hvis SSH dør mens stopped, Buddy fortsatt sender SIGCONT via signal-trap
  (Tinkla bash-shell på Buddy aldri eksiterer uten cleanup).
- T5 sender UDP-frame til Buddy port 20101 — det er port Buddy lytter på for
  EtherCAN-input. Vi spoofer en sandbox-CAN-ID 0x239 med unique payload
  `DEADBEEF11223344`. Worst case: Buddy logger eller forkaster.
- Ingen filendringer på Buddy. Ingen settings-toggling.
