#!/usr/bin/env bash
# Sync submodul-mirrors:
#   sveinmer/opendbc (privat) → sveinmer/nap-c3-opendbc (public)
#   sveinmer/panda   (privat) → sveinmer/nap-c3-panda   (public)
#
# Kjør FØR sync_to_public.sh hvis submodul-pin på nap-c3-dev har endret seg.
# Bruksmønster:
#   ./scripts/sync_submodules_to_public.sh              # oppdater dev
#   ./scripts/sync_submodules_to_public.sh --main       # oppdater også main

set -euo pipefail

UPDATE_MAIN=0
if [ "${1:-}" = "--main" ]; then
  UPDATE_MAIN=1
fi

REPO="/home/svein/repos/notautopilot"

sync_submodule() {
  local subdir="$1"             # opendbc_repo eller panda
  local source_branch="$2"      # nap-c3-dev eller nap-c3-dev-f4-rebuild
  local public_remote="$3"      # git@github.com:sveinmer/nap-c3-<X>.git
  local commit_msg="$4"
  local worktree="/tmp/${subdir}-public-prep-$(date +%s)"

  echo "=== Sync $subdir → $public_remote ==="
  cd "$REPO/$subdir"

  # Rydd evt. stale worktrees + public-snapshot-branch fra forrige sync-feil
  # NB: prune MÅ kjøre før branch -D — stale worktree holder branch-referanse låst
  git worktree prune
  # fjern også eksplisitt stale /tmp-worktrees (prune fjerner ikke alltid alle)
  for stale_wt in /tmp/${subdir}-public-prep-* /tmp/nap-c3-${subdir%_repo}-public; do
    [ -d "$stale_wt" ] && git worktree remove --force "$stale_wt" 2>/dev/null || true
    rm -rf "$stale_wt" 2>/dev/null || true
  done
  git worktree prune
  git branch -D public-snapshot 2>/dev/null || true

  # Lag detached worktree
  git worktree add --detach "$worktree" "$source_branch"
  cd "$worktree"

  # Sanitering (samme mønster som hovedrepo)
  { grep -rlE "192\.168\.0\.65|10\.213\.255\.154|<DONGLE_ID>|sveinmer@gmail" 2>/dev/null || true; } \
    | xargs -r -I{} sed -i \
      -e 's/192\.168\.0\.65/<C3_LAN_IP>/g' \
      -e 's/10\.213\.255\.154/<C3_LIVE_IP>/g' \
      -e 's/<DONGLE_ID>/<DONGLE_ID>/g' \
      -e 's/sveinmer@gmail\.com/noreply@cdma.no/g' {}

  { grep -rlE "\bSvein\b" 2>/dev/null || true; } \
    | xargs -r -I{} sed -i \
      -e 's/owner-go/owner-go/g' \
      -e 's/owner toggles/owner toggles/g' \
      -e 's/ — anonymisert i public-mirror

  # Squash + push
  git checkout --orphan public-snapshot
  git add -A
  git -c user.email=noreply@cdma.no -c user.name="NAP" \
    commit -m "$commit_msg snapshot $(date +%Y-%m-%d_%H%M)" \
    --author="NAP <noreply@cdma.no>"

  git remote add public "$public_remote" 2>/dev/null || true
  git push -f public public-snapshot:dev

  if [ "$UPDATE_MAIN" -eq 1 ]; then
    git push -f public public-snapshot:main
  fi

  # Cleanup
  cd "$REPO/$subdir"
  git worktree remove --force "$worktree"
}

sync_submodule "opendbc_repo" "nap-c3-dev" \
  "git@github.com:sveinmer/nap-c3-opendbc.git" \
  "opendbc for NAP nap-c3 —"

sync_submodule "panda" "nap-c3-dev-f4-rebuild" \
  "git@github.com:sveinmer/nap-c3-panda.git" \
  "panda F4-revive for NAP nap-c3 —"

echo ""
echo "=== Submoduler synkronisert. Kjør nå: ./scripts/sync_to_public.sh ==="
