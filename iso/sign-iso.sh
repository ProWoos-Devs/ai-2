#!/bin/bash
# Checksum an ISO and sign the checksum with the AI-2 package key.
#
# The ISO and its .sha256 sit side by side on the same release page, so
# whoever could replace one could replace the other; the checksum only proves
# the download was not corrupted. The signature is what ties the image to the
# same key that signs every AI-2 package (F1889E37B4E5FEC8), which people
# already trust through ai2-keyring.
#
# Runs on the LAPTOP: the key is here and nowhere else, and gpg will ask for
# the passphrase.
#
#   iso/sign-iso.sh path/to.iso        -> .iso.sha256 and .iso.sha256.sig
#
# Publish both beside the image, for the dated name and the stable name. To
# check one:
#   gpg --verify ai-2-x86_64.iso.sha256.sig ai-2-x86_64.iso.sha256
#   sha256sum -c ai-2-x86_64.iso.sha256
set -euo pipefail

KEY=F1889E37B4E5FEC8
ISO=${1:-}
[ -f "$ISO" ] || { echo "usage: $0 path/to.iso"; exit 2; }
command -v gpg >/dev/null || { echo "gpg is not installed"; exit 2; }
gpg --list-secret-keys "$KEY" >/dev/null 2>&1 || {
  echo "the signing key $KEY is not on this machine; run this on the laptop"; exit 2; }

cd "$(dirname "$ISO")"
base=$(basename "$ISO")
sha256sum "$base" > "$base.sha256"
rm -f "$base.sha256.sig"
gpg --local-user "$KEY" --detach-sign "$base.sha256"
gpg --verify "$base.sha256.sig" "$base.sha256"
sha256sum -c "$base.sha256"
echo
echo "Publish beside the image:  $base.sha256  $base.sha256.sig"
