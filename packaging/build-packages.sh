#!/bin/bash
# Build the AI-2 packages (unsigned) inside the ai2-artix-build container.
#
#   docker exec ai2-iso-build bash /ai2-repo/www/ai-2/packaging/build-packages.sh [pkg...]
#
# pkg is any of: ai2-keyring ai-2 ai2-llama-cpp (default: all three).
# Output: /ai2-repo/www/ai-2/packaging/out/*.pkg.tar.zst (gitignored).
# Signing is deliberately NOT done here; the key lives on the laptop, see
# sign-and-publish.sh.
set -euo pipefail

REPO=/ai2-repo
PKG_SRC=$REPO/www/ai-2/packaging
OUT=$PKG_SRC/out
WORK=/home/builder/pkgbuild
# Persistent source cache: the llama.cpp bare clone is ~2 GB, keep it across runs.
SRCDEST=/home/builder/srcdest
export MAKEFLAGS="-j$(nproc)"

pkgs=("$@")
[ ${#pkgs[@]} -eq 0 ] && pkgs=(ai2-keyring ai-2 ai2-llama-cpp)

if [ "$(id -u)" -eq 0 ]; then
  # makepkg refuses root; re-exec as builder (created in the image).
  exec sudo -u builder -E MAKEFLAGS="$MAKEFLAGS" bash "$0" "${pkgs[@]}"
fi

mkdir -p "$OUT" "$WORK" "$SRCDEST"

# The ai-2 tool tarball comes from git, so a package always maps to a commit.
# The repo is mounted read-only in spirit: git archive reads HEAD, and a dirty
# tree is refused unless AI2_ALLOW_DIRTY=1.
make_ai2_tarball() {
  local ver
  ver=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/www/ai-2/ai2/__init__.py")
  [ -n "$ver" ] || { echo "cannot read __version__" >&2; exit 1; }
  if [ -n "$(git -C "$REPO" status --porcelain -- www/ai-2 ':!www/ai-2/packaging/out')" ] \
     && [ "${AI2_ALLOW_DIRTY:-0}" != 1 ]; then
    echo "www/ai-2 has uncommitted changes; commit them or set AI2_ALLOW_DIRTY=1" >&2
    exit 1
  fi
  git -C "$REPO" archive --format=tar.gz --prefix="ai-2-$ver/" -o "$WORK/ai-2/ai-2-$ver.tar.gz" HEAD:www/ai-2
  echo "ai-2 tarball at $WORK/ai-2/ai-2-$ver.tar.gz (HEAD $(git -C "$REPO" rev-parse --short HEAD))"
  # keep the PKGBUILD's pkgver honest
  sed -i "s/^pkgver=.*/pkgver=$ver/" "$WORK/ai-2/PKGBUILD"
}

for p in "${pkgs[@]}"; do
  echo "=================== $p ==================="
  rm -rf "$WORK/$p"
  cp -a "$PKG_SRC/$p" "$WORK/$p"
  cd "$WORK/$p"
  [ "$p" = ai-2 ] && make_ai2_tarball
  # -s installs makedepends via sudo pacman; -f overwrites a stale package;
  # -C cleans an old srcdir so a changed source is never reused by accident.
  PKGDEST="$OUT" SRCDEST="$SRCDEST" makepkg -s -f -C --noconfirm
  echo "--- namcap ---"
  namcap PKGBUILD || true
  for f in "$OUT/$p"*.pkg.tar.zst; do namcap "$f" || true; done
done

echo
echo "Built packages in $OUT:"
ls -la "$OUT"/*.pkg.tar.zst
