#!/usr/bin/env bash
# Sync sveinmer/notautopilot (privat) → sveinmer/openpilot (public mirror).
#
# Kjør etter hver live-validert deploy på c3 for å oppdatere public-mirror.
# Public-mirror er det c3.cdma.no/dev installerer fra.
#
# Bruksmønster:
#   ./scripts/sync_to_public.sh              # oppdater bare dev-branch
#   ./scripts/sync_to_public.sh --main       # oppdater også main (stable release)
#
# Sanitering:
#   - Sletter docs/, docs-nap/, evidence/, .claude/, tools/preap_long/output/
#   - Sletter system/hardware/tici/id_rsa (GitHub Push Protection-trigger)
#   - Anonymiserer C3-IPs, dongle-ID, email, "Svein"-personnavn
#
# Submodul-mirrors må oppdateres separat via sync_submodules_to_public.sh.
#
# VIKTIG REKKEFØLGE (2026-05-25 lærdom):
#   Dette scriptet queryer GitHub API for nap-c3-opendbc/branches/main +
#   nap-c3-panda/branches/main for å sette submodul-pin. Hvis submodul-
#   endringer har skjedd, MÅ du kjøre sync_submodules_to_public.sh med
#   --main FØRST, ellers peker hovedrepo public main mot gammel submodul-
#   commit. Riktig sekvens for stable release:
#     1. ./scripts/sync_submodules_to_public.sh --main
#     2. ./scripts/sync_to_public.sh --main

set -euo pipefail

REPO="/home/svein/repos/notautopilot"
SOURCE_BRANCH="nap-c3-dev"
PUBLIC_REMOTE="git@github.com:sveinmer/openpilot.git"
WORKTREE="/tmp/nap-c3-public-prep-$(date +%s)"

UPDATE_MAIN=0
if [ "${1:-}" = "--main" ]; then
  UPDATE_MAIN=1
fi

cd "$REPO"

# 1. Verifiser at source branch er ren
if [ "$(git rev-parse --abbrev-ref HEAD)" != "$SOURCE_BRANCH" ]; then
  echo "WARN: ikke på $SOURCE_BRANCH (er på $(git rev-parse --abbrev-ref HEAD))"
  echo "Bytt branch eller skriv 'YES' for å fortsette:"
  read -r ans
  [ "$ans" = "YES" ] || exit 1
fi

# 2. Lag fresh detached worktree
echo "=== Lager worktree $WORKTREE ==="
git worktree add --detach "$WORKTREE" "$SOURCE_BRANCH"
cd "$WORKTREE"

# 3. Slett sensitive paths
echo "=== Sletter sensitive paths ==="
rm -rf docs/ docs-nap/ evidence/ .claude/ tools/preap_long/output/ 2>/dev/null || true
rm -f tinklaBuddy-R2S-1.44-*.img.gz* 2>/dev/null || true
rm -f system/hardware/tici/id_rsa 2>/dev/null || true

# 4. Anonymiser
echo "=== Anonymiserer IPs / dongle-ID / email ==="
{ grep -rlE "192\.168\.0\.65|10\.213\.255\.154|<DONGLE_ID>|sveinmer@gmail" 2>/dev/null || true; } \
  | xargs -r -I{} sed -i \
    -e 's/192\.168\.0\.65/<C3_LAN_IP>/g' \
    -e 's/10\.213\.255\.154/<C3_LIVE_IP>/g' \
    -e 's/<DONGLE_ID>/<DONGLE_ID>/g' \
    -e 's/sveinmer@gmail\.com/noreply@cdma.no/g' {}

# 5. Anonymiser personnavn "Svein"
echo "=== Anonymiserer 'Svein' personnavn ==="
{ grep -rlE "\bSvein\b" 2>/dev/null || true; } \
  | xargs -r -I{} sed -i \
    -e 's/owner-go/owner-go/g' \
    -e 's/owner toggles/owner toggles/g' \
    -e 's/ — anonymisert i public-mirror

# 6. Oppdater submodul-pin til public-mirror HEADs
echo "=== Oppdater submodul-pin til public-mirror HEADs ==="
OPENDBC_SHA=$(gh api /repos/sveinmer/nap-c3-opendbc/branches/main --jq .commit.sha)
PANDA_SHA=$(gh api /repos/sveinmer/nap-c3-panda/branches/main --jq .commit.sha)
echo "  opendbc public main: $OPENDBC_SHA"
echo "  panda public main:   $PANDA_SHA"

# 7. Rewrite .gitmodules til public URLs
cat > .gitmodules << EOF
[submodule "opendbc_repo"]
	path = opendbc_repo
	url = https://github.com/sveinmer/nap-c3-opendbc.git
	branch = main
[submodule "panda"]
	path = panda
	url = https://github.com/sveinmer/nap-c3-panda.git
	branch = main
[submodule "msgq_repo"]
	path = msgq_repo
	url = https://github.com/commaai/msgq.git
[submodule "rednose_repo"]
	path = rednose_repo
	url = https://github.com/commaai/rednose.git
[submodule "teleoprtc_repo"]
	path = teleoprtc_repo
	url = https://github.com/commaai/teleoprtc.git
[submodule "tinygrad_repo"]
	path = tinygrad_repo
	url = https://github.com/commaai/tinygrad.git
EOF

# 8. Squash til orphan-branch
echo "=== Squash til public-snapshot ==="
# Rydd evt. stale public-snapshot-branch fra forrige sync-feil
cd "$REPO"
git branch -D public-snapshot 2>/dev/null || true
git worktree prune
cd "$WORKTREE"
git checkout --orphan public-snapshot
git add -A
# Sett submodul-pin via update-index (ikke add)
git update-index --cacheinfo 160000,${OPENDBC_SHA},opendbc_repo
git update-index --cacheinfo 160000,${PANDA_SHA},panda

git -c user.email=noreply@cdma.no -c user.name="NAP" \
  commit -m "NAP for comma3 + 2014 Tesla S85 — snapshot $(date +%Y-%m-%d_%H%M)

Pre-AP NAP-fork basert på NotAutopilot/openpilot/nap-c3-dev.
Tinkla Buddy IC-integrasjon, comma-pedal long-control, F4 panda-firmware.

Submoduler:
  opendbc_repo -> sveinmer/nap-c3-opendbc
  panda        -> sveinmer/nap-c3-panda

Installer: https://c3.cdma.no/main eller /dev" \
  --author="NAP <noreply@cdma.no>"

# 9. Push til public dev (rolling)
echo "=== Push til sveinmer/openpilot dev ==="
git remote add public "$PUBLIC_REMOTE" 2>/dev/null || true
git push -f public public-snapshot:dev

# 10. Optional: push til main (stable release)
if [ "$UPDATE_MAIN" -eq 1 ]; then
  echo "=== Push til sveinmer/openpilot main (stable) ==="
  git push -f public public-snapshot:main
else
  echo ""
  echo "Public dev oppdatert. For stable release på main, kjør:"
  echo "  $0 --main"
fi

# 11. Cleanup worktree
cd "$REPO"
echo ""
echo "=== Cleanup worktree ==="
git worktree remove --force "$WORKTREE"
echo "Ferdig."
