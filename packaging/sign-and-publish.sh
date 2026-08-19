#!/bin/bash
# Sign freshly built AI-2 packages, update the [ai2] repo database, and
# publish the repo to GitHub Releases. Runs on the LAPTOP (the signing key
# lives here, never in the container or on a server).
#
#   sign-and-publish.sh            sign out/*.pkg.tar.zst, update db, upload
#   sign-and-publish.sh --no-push  sign + update the local repo only
#   (with nothing in out/ it just re-publishes the current repo state)
#
# Layout (gitignored): packaging/repo/x86_64/ is the authoritative local copy
# of the published repo (packages, .sig files, ai2.db, ai2.files). GitHub
# release "x86_64" on ProWoos-Devs/ai2-packages mirrors it, so pacman's
#   Server = https://github.com/ProWoos-Devs/ai2-packages/releases/download/x86_64
# resolves $Server/ai2.db and $Server/<pkg>.pkg.tar.zst directly.
set -euo pipefail

KEY=F1889E37B4E5FEC8
GH_REPO=ProWoos-Devs/ai2-packages
RELEASE=x86_64
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$HERE/out
REPO=$HERE/repo/$RELEASE
DB=ai2.db.tar.gz

push=1
[ "${1:-}" = --no-push ] && push=0

mkdir -p "$REPO"
shopt -s nullglob
# New = whatever is in out/, plus any package already in the repo dir that has
# no valid signature (a previous run that died at the gpg prompt leaves exactly
# that behind; 2026-08-19).
new=("$OUT"/*.pkg.tar.zst)
for p in "$REPO"/*.pkg.tar.zst; do
  if [ ! -f "$p.sig" ] || ! gpg --verify "$p.sig" "$p" >/dev/null 2>&1; then
    echo "unsigned in repo dir, will sign: $(basename "$p")"
    new+=("$p")
  fi
done
if [ ${#new[@]} -eq 0 ]; then
  echo "nothing new in $OUT; re-publishing current repo state"
  [ -f "$REPO/$DB" ] || { echo "no repo db yet" >&2; exit 1; }
fi

# 1. Copy new packages into the repo dir and detach-sign each one; the copy
#    in out/ is removed only once the signature verifies.
for f in "${new[@]}"; do
  b=$(basename "$f")
  [ "$f" = "$REPO/$b" ] || cp -f "$f" "$REPO/$b"
  rm -f "$REPO/$b.sig"
  gpg --batch --yes --detach-sign --use-agent -u "$KEY" "$REPO/$b"
  gpg --verify "$REPO/$b.sig" "$REPO/$b" 2>/dev/null && echo "signed  $b"
  [ "$f" = "$REPO/$b" ] || rm -f "$f"
done

# 2. Update the database (verifies the package signatures, signs the db).
cd "$REPO"
if [ ${#new[@]} -gt 0 ]; then
  repo-add --verify --sign --key "$KEY" --remove "$DB" "${new[@]/#*\//}"
fi

# 3. Drop package files no longer referenced by the db (repo-add --remove
#    deletes superseded versions itself; this catches strays).
for p in *.pkg.tar.zst; do
  tar -tf "$DB" 2>/dev/null | grep -q "^${p%-*-*.pkg.tar.zst}-" || echo "warning: $p not in db"
done

# repo-add leaves ai2.db / ai2.files (+ .sig) as symlinks to the .tar.gz
# files. GitHub release assets cannot be symlinks and pacman fetches exactly
# those names, so replace them with real copies.
rm -f ai2.db ai2.db.sig ai2.files ai2.files.sig
cp "$DB" ai2.db;               cp "$DB.sig" ai2.db.sig
cp ai2.files.tar.gz ai2.files; cp ai2.files.tar.gz.sig ai2.files.sig

echo; echo "Repo state in $REPO:"; ls -la

[ $push -eq 1 ] || { echo "(--no-push) done"; exit 0; }

# 4. Publish. The release is a rolling one; --clobber replaces assets in place.
if ! gh release view "$RELEASE" -R "$GH_REPO" >/dev/null 2>&1; then
  gh release create "$RELEASE" -R "$GH_REPO" --title "AI-2 package repo ($RELEASE)" \
    --notes "Rolling pacman repository for AI-2. Do not download by hand; add the [ai2] repo to pacman.conf (see the README)."
fi
gh release upload "$RELEASE" -R "$GH_REPO" --clobber \
  ai2.db ai2.db.sig ai2.files ai2.files.sig "$DB" "$DB.sig" ai2.files.tar.gz ai2.files.tar.gz.sig \
  *.pkg.tar.zst *.pkg.tar.zst.sig
echo "published to https://github.com/$GH_REPO/releases/tag/$RELEASE"
