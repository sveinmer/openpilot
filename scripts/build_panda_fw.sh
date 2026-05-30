#!/usr/bin/env bash
# Build the F4 panda firmware for C3 (Tesla Pre-AP NAP) and optionally commit
# the resulting blobs into the panda submodule.
#
# This is the wrapper for sveinmer/panda branch nap-c3-dev-f4-rebuild — see
# evidence/panda_fase7_build/README.md for the full rotårsak / fix dossier
# that the branch encodes.
#
# Usage:
#   scripts/build_panda_fw.sh               # build + show md5 + diff vs committed
#   scripts/build_panda_fw.sh --commit      # build + git add+commit obj/ in panda
#   scripts/build_panda_fw.sh --commit --push  # same + push panda submodule
#
# Toolchain detection (in priority order):
#   1. $ARM_GCC and $SCONS env vars (explicit override)
#   2. arm-none-eabi-gcc / scons on $PATH (apt/pip-installed)
#   3. Dev-box defaults: /home/svein/.local/arm-gcc/usr/bin, $NAP/.venv/bin/scons
#
# Install hints if step 2+3 both fail:
#   Debian/Ubuntu: apt install gcc-arm-none-eabi scons python3-pycryptodome
#   pip:           pip install scons pycryptodome

set -euo pipefail

NAP="$(git rev-parse --show-toplevel)"
PANDA="$NAP/panda"

# --- toolchain detection ---
find_arm_gcc() {
  if [ -n "${ARM_GCC:-}" ] && [ -x "$ARM_GCC" ]; then echo "$ARM_GCC"; return; fi
  if command -v arm-none-eabi-gcc >/dev/null 2>&1; then command -v arm-none-eabi-gcc; return; fi
  if [ -x /home/svein/.local/arm-gcc/usr/bin/arm-none-eabi-gcc ]; then
    echo /home/svein/.local/arm-gcc/usr/bin/arm-none-eabi-gcc; return
  fi
  return 1
}
find_scons() {
  if [ -n "${SCONS:-}" ] && [ -x "$SCONS" ]; then echo "$SCONS"; return; fi
  if command -v scons >/dev/null 2>&1; then command -v scons; return; fi
  if [ -x "$NAP/.venv/bin/scons" ]; then echo "$NAP/.venv/bin/scons"; return; fi
  return 1
}

ARM_GCC="$(find_arm_gcc)" || {
  echo "ERROR: arm-none-eabi-gcc not found." >&2
  echo "  Install: apt install gcc-arm-none-eabi  (or set ARM_GCC=/path/to/arm-none-eabi-gcc)" >&2
  exit 1
}
SCONS="$(find_scons)" || {
  echo "ERROR: scons not found." >&2
  echo "  Install: apt install scons  (or pip install scons; or set SCONS=/path/to/scons)" >&2
  exit 1
}
ARM_GCC_BIN="$(dirname "$ARM_GCC")"

DO_COMMIT=0
DO_PUSH=0
for arg in "$@"; do
  case "$arg" in
    --commit) DO_COMMIT=1 ;;
    --push)   DO_PUSH=1 ;;
    -h|--help)
      sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

[ -d "$PANDA/board/stm32f4" ] || { echo "ERROR: panda submodule not on a branch with F4 build support (board/stm32f4/ missing). Expected: nap-c3-dev-f4-rebuild." >&2; exit 1; }

cd "$PANDA"

EXPECTED_BRANCH="nap-c3-dev-f4-rebuild"
ACTUAL_BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo DETACHED)"
if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "WARN: panda submodule HEAD is on '$ACTUAL_BRANCH', expected '$EXPECTED_BRANCH'."
  echo "      Build will proceed, but commit/push will refuse to run."
fi

echo "=== Building F4 panda firmware ==="
echo "  panda commit: $(git rev-parse --short HEAD)"
echo "  arm-gcc:      $ARM_GCC"
echo "                $($ARM_GCC --version | head -1)"
echo "  scons:        $SCONS"
echo "                $($SCONS --version 2>&1 | head -1)"

PATH="$ARM_GCC_BIN:$PATH" \
PYTHONPATH="$NAP:$NAP/opendbc_repo" \
  "$SCONS" -Q --cache-disable -j4 \
    board/obj/panda.bin.signed \
    board/obj/bootstub.panda.bin

echo
echo "=== Build output ==="
ls -l board/obj/panda.bin.signed board/obj/bootstub.panda.bin
md5sum board/obj/panda.bin.signed board/obj/bootstub.panda.bin

echo
echo "=== gitversion in firmware ==="
cat board/obj/version 2>/dev/null && echo

# Detect whether the committed obj/ differs from what we just built.
STATUS="$(git status --porcelain -- board/obj/panda.bin.signed board/obj/bootstub.panda.bin)"
if [ -z "$STATUS" ]; then
  echo "=== Build matches committed obj/ (no diff) ==="
  exit 0
fi

echo
echo "=== Build differs from committed obj/ ==="
git diff --stat -- board/obj/panda.bin.signed board/obj/bootstub.panda.bin
echo
echo "(Build differing from committed is expected if the panda commit hash"
echo " changed — gitversion is baked in. See evidence/panda_fase7_build/"
echo " README.md for context.)"

if [ "$DO_COMMIT" -eq 0 ]; then
  echo
  echo "Rerun with --commit to update obj/ in the panda submodule."
  exit 0
fi

if [ "$ACTUAL_BRANCH" != "$EXPECTED_BRANCH" ]; then
  echo "ERROR: refusing to --commit on branch '$ACTUAL_BRANCH'. Checkout $EXPECTED_BRANCH first." >&2
  exit 1
fi

GITVERSION="$(cat board/obj/version 2>/dev/null || echo unknown)"
PANDA_MD5="$(md5sum board/obj/panda.bin.signed | awk '{print $1}')"
BOOTSTUB_MD5="$(md5sum board/obj/bootstub.panda.bin | awk '{print $1}')"

git add board/obj/panda.bin.signed board/obj/bootstub.panda.bin
git commit -m "[firmware] rebuild F4 panda from $(git rev-parse --short HEAD~0)

gitversion: $GITVERSION
panda.bin.signed   md5=$PANDA_MD5   $(stat -c %s board/obj/panda.bin.signed) B
bootstub.panda.bin md5=$BOOTSTUB_MD5   $(stat -c %s board/obj/bootstub.panda.bin) B

Built by scripts/build_panda_fw.sh." >&2

echo
echo "=== Committed in panda submodule ==="
git log --oneline -1

if [ "$DO_PUSH" -eq 1 ]; then
  echo
  echo "=== Pushing panda submodule ==="
  git push sveinmer "$EXPECTED_BRANCH"
fi

echo
echo "NEXT: in $NAP, run:"
echo "  git add panda"
echo "  git commit -m \"panda submodul: rebuild F4 firmware ($GITVERSION)\""
[ "$DO_PUSH" -eq 0 ] && echo "  (and push the panda submodule too: cd panda && git push sveinmer $EXPECTED_BRANCH)"
