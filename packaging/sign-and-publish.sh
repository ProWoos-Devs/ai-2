#!/bin/bash
# Sign freshly built AI-2 packages, update the [ai2] repo database, and
# publish the repo to GitHub Releases. Runs on the LAPTOP (the signing key
# lives here, never in the container or on a server).
#
#   sign-and-publish.sh            sign out/*.pkg.tar.zst, update db, upload
#   sign-and-publish.sh --no-push  sign + update the local repo only
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
new=("$OUT"/*.pkg.tar.zst)
if [ ${#new[@]} -eq 0 ]; then
  echo "nothing in $OUT to publish" >&2; exit 1
fi

# 1. Move new packages into the repo dir and detach-sign each one.
for f in "${new[@]}"; do
  b=$(basename "$f")
  mv -f "$f" "$REPO/$b"
  rm -f "$REPO/$b.sig"
  gpg --batch --yes --detach-sign --use-agent -u "$KEY" "$REPO/$b"
  gpg --verify "$REPO/$b.sig" "$REPO/$b" 2>/dev/null && echo "signed  $b"
done

# 2. Update the database (verifies the package signatures, signs the db).
cd "$REPO"
repo-add --verify --sign --key "$KEY" --remove "$DB" "${new[@]/#*\//}"

# 3. Drop package files no longer referenced by the db (repo-add --remove
#    deletes superseded versions itself; this catches strays).
for p in *.pkg.tar.zst; do
  tar -tf "$DB" 2>/dev/null | grep -q "^${p%-*-*.pkg.tar.zst}-" || echo "warning: $p not in db"
done

# GitHub release assets cannot be symlinks; pacman fetches ai2.db / ai2.files
# by those names, so publish real copies alongside the .tar.gz originals.
cp -f "$DB" ai2.db;               cp -f "$DB.sig" ai2.db.sig
cp -f ai2.files.tar.gz ai2.files; cp -f ai2.files.tar.gz.sig ai2.files.sig

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
