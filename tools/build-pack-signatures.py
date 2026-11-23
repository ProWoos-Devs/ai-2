#!/usr/bin/env python3
"""Write ai2/data/signatures/<id>.sig, one file for every Knowledge Pack in
ai2/data/packs.yml.

A signature is the search vectors of a Knowledge Pack, made small. The chat
uses it to tell whether a Knowledge Pack that is not on the computer would
show a passage for a question once installed, without downloading anything
and without asking the search model again (ai2/packsig.py). The files ship
inside the ai-2 package beside the catalog, so each one is pinned to the
SHA-256 of the pack file it was made from.

  python3 tools/build-pack-signatures.py PACKS_DIR   from a working copy of
                                                     ai2-knowledge, its packs/
  python3 tools/build-pack-signatures.py             downloads every pack file
  python3 tools/build-pack-signatures.py --check     say whether the files
                                                     match the catalog, write
                                                     nothing, read no pack
  python3 tools/build-pack-signatures.py --help      print this, do nothing

tools/sync-pack-catalog.py runs this as its last step, so one command before
a release refreshes both. `--check` is what the package build runs. Exit 0
current, 1 not, 2 for an option this does not know, which does nothing.

The file, format 1:
  line 1   JSON, UTF-8, ending in a newline, with the keys
           format, id, revision, pack_sha256, model, dims, count, body_sha256
  then     count little-endian float32, the length of each stored vector
  then     count x dims signed bytes, documents by name, parts in order

Each part vector is cut to its first DIMS numbers, brought back to length 1,
and the whole pack is scaled by one factor so its largest number becomes 127.
Standard library and yaml only, no search model is needed.
"""
import array
import hashlib
import json
import math
import os
import sqlite3
import sys
import tempfile
import urllib.request
import zipfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATALOG = os.path.join(ROOT, "ai2", "data", "packs.yml")
SIG_DIR = os.path.join(ROOT, "ai2", "data", "signatures")
FORMAT = 1
DIMS = 768
SUFFIX = ".sig"
# No index of a Knowledge Pack comes near this; a file that claims more is not read.
MAX_INDEX_BYTES = 512 * 1024 * 1024


# What a catalog entry must carry for a signature to be made or checked.
ENTRY_KEYS = ("id", "revision", "sha256", "embedder", "parts")


class Stop(Exception):
    """A pack file or a signature is not what the catalog says."""


def entries(catalog: str = CATALOG) -> list[dict]:
    data = yaml.safe_load(open(catalog, encoding="utf-8")) or {}
    return list(data.get("packs") or [])


def header(entry: dict, dims: int) -> dict:
    """What line 1 of an entry's file must say, all but body_sha256, which is
    the SHA-256 of everything after line 1 and so cannot be told from the
    catalog."""
    missing = [key for key in ENTRY_KEYS if entry.get(key) is None]
    if missing:
        raise Stop(f"{entry.get('id') or 'an entry'}: the catalog entry has no " + ", ".join(missing))
    return {"format": FORMAT, "id": entry["id"], "revision": entry["revision"], "pack_sha256": entry["sha256"],
            "model": entry["embedder"], "dims": dims, "count": entry["parts"]}


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(entry: dict, dest_dir: str) -> str:
    """Download an entry's pack file. https only, and never more than the
    catalog says the file holds."""
    url = str(entry.get("url") or "")
    if not url.startswith("https://"):
        raise Stop(f"{entry['id']}: the url is not https")
    path = os.path.join(dest_dir, os.path.basename(url))
    limit = int(entry.get("size_bytes") or 0)
    req = urllib.request.Request(url, headers={"User-Agent": "ai-2"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
            if not r.geturl().startswith("https://"):
                raise Stop(f"{entry['id']}: the download left https")
            got = 0
            for block in iter(lambda: r.read(1 << 16), b""):
                got += len(block)
                if limit and got > limit:
                    raise Stop(f"{entry['id']}: the download is larger than the catalog says")
                f.write(block)
    except OSError as exc:
        raise Stop(f"{entry['id']}: could not download {url} ({exc})") from exc
    return path


def part_vectors(pack_file: str) -> tuple[str, list[bytes]]:
    """The search model a pack file was built with and its part vectors as
    stored, documents by name, parts in order."""
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(pack_file) as z:
            if z.getinfo("index.sqlite").file_size > MAX_INDEX_BYTES:
                raise Stop(f"{pack_file}: the index is too large to be a Knowledge Pack")
            z.extract("index.sqlite", tmp)
        conn = sqlite3.connect(os.path.join(tmp, "index.sqlite"))
        try:
            model = conn.execute("SELECT value FROM meta WHERE key = 'model'").fetchone()[0]
            blobs = [blob for (blob,) in conn.execute(
                "SELECT chunks.vec FROM chunks JOIN docs ON docs.id = chunks.doc_id "
                "ORDER BY docs.name, chunks.ord")]
        finally:
            conn.close()
    return model, blobs


def signature(entry: dict, pack_file: str, dims: int = DIMS) -> bytes:
    """The bytes of an entry's signature file, from its pack file. Stops when
    the file is not the one the catalog describes."""
    head = header(entry, dims)
    pid = entry["id"]
    if not os.path.isfile(pack_file):
        raise Stop(f"{pid}: {pack_file} is not there")
    digest = sha256_file(pack_file)
    if digest != entry["sha256"]:
        raise Stop(f"{pid}: {pack_file} has SHA-256 {digest}, the catalog says {entry['sha256']}")
    try:
        model, blobs = part_vectors(pack_file)
    except (zipfile.BadZipFile, KeyError, sqlite3.Error, TypeError) as exc:
        raise Stop(f"{pid}: {pack_file} could not be read as a Knowledge Pack ({exc})") from exc
    if model != entry["embedder"]:
        raise Stop(f"{pid}: built with {model}, the catalog says {entry['embedder']}")
    if len(blobs) != entry["parts"]:
        raise Stop(f"{pid}: {len(blobs)} parts, the catalog says {entry['parts']}")
    if not blobs:
        raise Stop(f"{pid}: no parts")
    vectors = []
    for blob in blobs:
        v = array.array("f")
        v.frombytes(blob)
        if sys.byteorder != "little":
            v.byteswap()
        if len(v) < dims:
            raise Stop(f"{pid}: a part vector has {len(v)} numbers, {dims} are needed")
        v = v[:dims]
        length = math.sqrt(sum(x * x for x in v)) or 1.0
        vectors.append([x / length for x in v])
    scale = max(abs(x) for v in vectors for x in v) or 1.0
    ints = [array.array("b", (int(round(x / scale * 127)) for x in v)) for v in vectors]
    norms = array.array("f", (math.sqrt(sum(x * x for x in v)) for v in ints))
    if sys.byteorder != "little":
        norms.byteswap()
    body = norms.tobytes() + b"".join(v.tobytes() for v in ints)
    head["body_sha256"] = hashlib.sha256(body).hexdigest()
    return json.dumps(head, separators=(",", ":")).encode("utf-8") + b"\n" + body


def stray(catalog_entries: list[dict], sig_dir: str) -> list[str]:
    """Signature files that belong to no catalog entry."""
    wanted = {str(e.get("id")) + SUFFIX for e in catalog_entries}
    if not os.path.isdir(sig_dir):
        return []
    return sorted(n for n in os.listdir(sig_dir) if n.endswith(SUFFIX) and n not in wanted)


def build(catalog_entries: list[dict], packs_dir: str | None, sig_dir: str = SIG_DIR, dims: int = DIMS) -> int:
    """Rewrite every signature file and remove the ones with no entry. Every
    file is worked out before any is written, so a pack that does not match
    the catalog leaves the directory as it was."""
    made = {}
    with tempfile.TemporaryDirectory() as tmp:
        for e in catalog_entries:
            header(e, dims)                # stops here when the entry is not whole
            if packs_dir:
                pack_file = os.path.join(packs_dir, e["id"], os.path.basename(str(e.get("url") or "")))
            else:
                pack_file = fetch(e, tmp)
            made[e["id"]] = signature(e, pack_file, dims)
    os.makedirs(sig_dir, exist_ok=True)
    total = 0
    for pid, data in made.items():
        path = os.path.join(sig_dir, pid + SUFFIX)
        with open(path + ".new", "wb") as f:
            f.write(data)
        os.replace(path + ".new", path)
        total += len(data)
        print(f"  {pid}: {len(data)} bytes")
    for name in stray(catalog_entries, sig_dir):
        os.remove(os.path.join(sig_dir, name))
        print(f"  removed {name}, the catalog has no such Knowledge Pack")
    print(f"{sig_dir}: {len(made)} signature(s), {total} bytes")
    return 0


def problems(catalog_entries: list[dict], sig_dir: str = SIG_DIR, dims: int = DIMS) -> list[str]:
    """Why the signature files are not the ones for this catalog; empty when
    they are. Reads no pack file. The first line must be the one the catalog
    entry asks for, and the rest of the file must have the length and the
    SHA-256 that line gives, so a file whose vectors were damaged after it was
    made is told too."""
    found = []
    for e in catalog_entries:
        try:
            want = header(e, dims)
        except Stop as exc:
            found.append(str(exc))
            continue
        path = os.path.join(sig_dir, e["id"] + SUFFIX)
        if not os.path.isfile(path):
            found.append(f"{e['id']}: no signature")
            continue
        with open(path, "rb") as f:
            line = f.readline(4096)
            body = f.read()
        try:
            head = json.loads(line.decode("utf-8")) if line.endswith(b"\n") else None
        except ValueError:
            head = None
        if not isinstance(head, dict):
            found.append(f"{e['id']}: the signature has no readable first line")
            continue
        differ = [k for k in want if head.get(k) != want[k] or type(head.get(k)) is not type(want[k])]
        if differ or set(head) != set(want) | {"body_sha256"}:
            found.append(f"{e['id']}: the signature is for another " + (", ".join(differ) or "format"))
            continue
        size = 4 * want["count"] + dims * want["count"]
        if len(body) != size:
            found.append(f"{e['id']}: the signature is {len(line) + len(body)} bytes, not {len(line) + size}")
        elif hashlib.sha256(body).hexdigest() != head["body_sha256"]:
            found.append(f"{e['id']}: the vectors in the signature are not the ones it was written with")
    found += [f"{name}: the catalog has no such Knowledge Pack" for name in stray(catalog_entries, sig_dir)]
    return found


USAGE = "usage: python3 tools/build-pack-signatures.py [PACKS_DIR | --check | --help]"


def main(argv: list[str]) -> int:
    options = [a for a in argv if a.startswith("-")]
    args = [a for a in argv if not a.startswith("-")]
    if "--help" in options or "-h" in options:
        print(__doc__.strip())
        return 0
    check = options == ["--check"]
    # An option this does not know must never fall through to the download.
    if (options and not check) or len(args) > 1 or (check and args):
        print(USAGE)
        return 2
    catalog_entries = entries(CATALOG)
    if check:
        found = problems(catalog_entries, SIG_DIR, DIMS)
        for line in found:
            print("  " + line)
        if found:
            print(f"{SIG_DIR} does not match the catalog. Make the files again with")
            print("  python3 tools/build-pack-signatures.py PACKS_DIR")
            return 1
        print(f"{SIG_DIR} matches the catalog ({len(catalog_entries)} signature(s))")
        return 0
    try:
        return build(catalog_entries, args[0] if args else None, SIG_DIR, DIMS)
    except Stop as exc:
        print(f"error: {exc}")
        print("nothing was written")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
