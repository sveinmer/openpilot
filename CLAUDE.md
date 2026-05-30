# NAP C3 Dev - Claude Bootstrap

Dette er Sveins private Not-Auto-Pilot fork for en 2014 Tesla Model S85
(tech-pakke, non-P) med comma 3. Hovedlinje: `nap-c3-dev`.

## Arbeidsform

- Bruk norsk.
- Svein: programmering begynner, nettverk ekspert, bilelektronikk avansert.
- Les `.claude/memory/user_language.md` og
  `.claude/memory/user_svein_competence.md`.
- **Rolle-kontrakt (oppdatert 2026-05-07):** Svein er sjef/eier. Claude er
  sjefsarkitekt for NAP. Codex er fjernet fra prosjektet. Claude lager og
  kanoniserer sprintplaner, findings, handover og memory selv. Tidligere
  rolle-grense ("Claude er kodeagent, ikke arkitekt") er **superseded**.
  Se [.claude/memory/user_role_change_2026_05_07_claude_chief_architect.md](.claude/memory/user_role_change_2026_05_07_claude_chief_architect.md).

## Start Hver Økt

1. Les `.claude/memory/MEMORY.md`, spesielt `START HER`.
2. Les `docs/NAP_C3_DEV_CANONICAL_PLAN.md`.
3. Les nyeste primærkilde/funn som MEMORY peker til.
4. Sjekk `git branch --show-current`, `git status --short`,
   `git log --oneline -5`.
5. Ved C3/device-sprint: les relevant sprintplan/funn og C3-endpoint memory.

## Sprintprotokoll

Se `.claude/SPRINT_PROTOCOL.md` for sesjonsstart, sprintarbeid,
handover, memory-oppdatering, commit og push.

## Kilder

- `.claude/memory/MEMORY.md` er memory-index.
- `docs/NAP_C3_DEV_CANONICAL_PLAN.md` er kanonisk arkitektur- og safety-plan.
- `docs/NAP_FIX_*_SPRINT.md` er Claude-arkitektgodkjente sprintkontrakter
  (tidligere Codex-godkjente; rolle-endring 2026-05-07).
- `docs/NAP_FIX_*_FINDINGS*.md` og `docs/NAP_HANDOVER_*.md` er evidence og
  handover.
- Memory persisteres i repoet; ikke stol på lokal Claude-cache som eneste
  kilde.

## Sikkerhet

- Privat fork: ikke "rydd opp" i uvanlige NAP-valg uten bevis.
- Ikke gjett hardware eller safety-state.
- For safety-kritiske ting: les hele kausalkjeden.
- Følg `.claude/memory/feedback_*`.
