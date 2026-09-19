#!/usr/bin/env python3
"""Refresh ai2/data/packs.yml from the community catalog.

The ai-2 package carries a copy of the community catalog, and a pack is
installed by name only from that copy, because the signature on the package is
what vouches for the hashes in it. So a pack merged into the catalog reaches
`ai-2 knowledge available` when a release is cut with a fresh copy. Run this
before every ai-2 release, read the diff, and commit it.

  python3 tools/sync-pack-catalog.py                 from GitHub
  python3 tools/sync-pack-catalog.py PATH/community.yml   from a working copy
  python3 tools/sync-pack-catalog.py --check         say whether the copy is
                                                     current, write nothing

`--check` is what the package build runs: a release whose copy is behind the
catalog ships packs nobody can install by name yet, and that is invisible
until somebody tries. Exit 0 current, 1 behind, 2 could not be checked (no
network, which never fails a build).
"""
import os
import sys
import urllib.request

import yaml

SOURCE = "https://raw.githubusercontent.com/ProWoos-Devs/ai2-knowledge/main/catalog/community.yml"
TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai2", "data", "packs.yml")
HEADER = """# Knowledge Packs AI-2 can install by name (`ai-2 knowledge install ID`).
#
# This is a copy of the AI-2 community catalog, which lists every pack, the
# project's own included:
# https://github.com/ProWoos-Devs/ai2-knowledge/blob/main/catalog/community.yml
# It ships inside the ai-2 package, which is signed, so the SHA-256 of every
# pack here is covered by the repository key: the file that arrives is the file
# the catalog described when this release was cut. `contact` is who made the
# pack. Getting packs, and sharing one you made:
# https://github.com/ProWoos-Devs/ai2-knowledge
#
# Do not edit by hand. tools/sync-pack-catalog.py writes it before a release.
"""


def main() -> int:
    check = "--check" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        text = open(args[0], encoding="utf-8").read()
    else:
        try:
            with urllib.request.urlopen(SOURCE, timeout=30) as r:
                text = r.read().decode("utf-8")
        except OSError as exc:
            if check:
                print(f"could not read the catalog ({exc}); not checked")
                return 2
            raise
    data = yaml.safe_load(text) or {}
    packs = data.get("packs") or []
    if data.get("version") != 1 or not packs:
        print("error: that is not a version 1 catalog with packs in it")
        return 1
    body = yaml.safe_dump({"version": 1, "packs": packs}, allow_unicode=True, sort_keys=False, width=120)
    if check:
        here = open(TARGET, encoding="utf-8").read()
        if here == HEADER + body:
            print(f"{TARGET} is the catalog as it stands ({len(packs)} pack(s))")
            return 0
        mine = {p["id"]: p for p in (yaml.safe_load(here) or {}).get("packs") or []}
        theirs = {p["id"]: p for p in packs}
        for pid in sorted(set(theirs) - set(mine)):
            print(f"  the catalog has {pid}, this copy does not")
        for pid in sorted(set(mine) - set(theirs)):
            print(f"  this copy has {pid}, the catalog does not")
        for pid in sorted(set(mine) & set(theirs)):
            if mine[pid] != theirs[pid]:
                print(f"  {pid} differs (revision here {mine[pid].get('revision')}, "
                      f"in the catalog {theirs[pid].get('revision')})")
        print(f"{TARGET} is not the catalog as it stands; run: python3 tools/sync-pack-catalog.py")
        return 1
    open(TARGET, "w", encoding="utf-8").write(HEADER + body)
    print(f"{TARGET}: {len(packs)} pack(s): " + ", ".join(p["id"] for p in packs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
