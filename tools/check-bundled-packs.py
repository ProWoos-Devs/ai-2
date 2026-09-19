#!/usr/bin/env python3
"""The packs staged into the image are the files the packaged catalog says.

`iso/packs/*.ai2pack` go into /etc/skel, and `ai2/data/packs.yml` is what the
tool checks a download against. If the two disagree, a fresh install carries a
pack whose checksum does not match the one every other install path verifies.
A unit test checks this too; the package build runs this so a release cannot
be cut around a failing test.
"""
from __future__ import annotations

import hashlib
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    catalog = yaml.safe_load((ROOT / "ai2/data/packs.yml").read_text())
    entries = {p["id"]: p for p in (catalog or {}).get("packs") or []}
    files = sorted((ROOT / "iso/packs").glob("*.ai2pack"))
    problems = []
    if {f.stem for f in files} != set(entries):
        problems.append(f"iso/packs has {sorted(f.stem for f in files)}, "
                        f"the catalog has {sorted(entries)}")
    for f in files:
        entry = entries.get(f.stem)
        if entry is None:
            continue
        data = f.read_bytes()
        if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
            problems.append(f"{f.name}: sha256 does not match the catalog entry")
        elif len(data) != entry.get("size_bytes"):
            problems.append(f"{f.name}: {len(data)} bytes, the catalog says {entry.get('size_bytes')}")
    for p in problems:
        print("  " + p)
    if problems:
        print("iso/packs and ai2/data/packs.yml disagree")
        return 1
    print(f"iso/packs matches the catalog ({len(files)} pack(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
