Everything AI-2 publishes is signed with one key, and this page says how to check each piece yourself: the installation image, the packages, and older versions if you want to stay on one.

## The signing key

**AI-2 Package Signing**, an Ed25519 key.

```
Fingerprint: 0895 C4AA 07DA 5912 6D7F  6F3E F188 9E37 B4E5 FEC8
Key ID:      F1889E37B4E5FEC8
```

The public key is published in the package repository, https://github.com/ProWoos-Devs/ai2-packages (file `ai2-package-signing.asc`), and ships inside the `ai2-keyring` package on every AI-2 system. Before you trust it, check that the fingerprint gpg shows is the one above:

```bash
curl -fsSL https://raw.githubusercontent.com/ProWoos-Devs/ai2-packages/main/ai2-package-signing.asc -o ai2-key.asc
gpg --show-keys --with-fingerprint ai2-key.asc
gpg --import ai2-key.asc
```

## The installation image

Every release on the [Releases page](https://github.com/ProWoos-Devs/ai-2/releases) has three files per name, the image, its SHA-256 checksum, and a signature of that checksum. The same files are mirrored on [SourceForge](https://sourceforge.net/projects/ai-2/).

```bash
sha256sum -c ai-2-x86_64.iso.sha256
gpg --verify ai-2-x86_64.iso.sha256.sig ai-2-x86_64.iso.sha256
```

The first line proves the download is complete and unchanged. The second proves the checksum is the one the AI-2 key signed; it should report a good signature from `F1889E37B4E5FEC8`. Checking only the checksum is not enough on its own, because anyone who could replace the image on a download page could replace its checksum too.

The dated files (`artix-ai2-runit-YYYYMMDD-x86_64.iso`) are the same image under its build date, with their own checksum and signature.

## Packages

AI-2's packages come from the `[ai2]` repository, which `pacman.conf` lists as:

```
[ai2]
SigLevel = Required DatabaseOptional
Server = https://github.com/ProWoos-Devs/ai2-packages/releases/download/x86_64
```

`Required` means pacman refuses any package from it that does not carry a valid signature from a trusted key; there is no way to install an unsigned AI-2 package from the repository by accident. The repository database is signed as well. To see how an installed package was checked:

```bash
pacman -Qi ai-2 | grep "Validated By"
```

It should say `Signature` (or `SHA-256 Sum  Signature`).

## Staying on a version

**An older package.** Older `ai-2` packages stay in the repository release, every one from 0.3.0 on. Install one by its address; pacman fetches its signature beside it and checks it the same way:

```bash
sudo pacman -U https://github.com/ProWoos-Devs/ai2-packages/releases/download/x86_64/ai-2-0.19.1-1-any.pkg.tar.zst
```

To keep it from being updated, add `ai-2` to the `IgnorePkg` line in `/etc/pacman.conf`, and remove it from there when you want updates again. AI-2 is a rolling release, so holding a package back for long is not recommended.

**An older image.** The Releases page keeps the most recent images. Every image ever released keeps its git tag (`iso-YYYYMMDD`), so an older one can be rebuilt from the `iso/` profile at that tag; the build needs Artix Linux's `artools`.

## What AI-2 does not do

- No `curl | bash` installer. The only `curl` in the instructions fetches the public key, which you check against the fingerprint above.
- No unsigned packages in the repository, and no repository configured to accept them.
- No account and no telemetry. AI-2 sends nothing about you or your computer anywhere.
