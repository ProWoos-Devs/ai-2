"""Would a Knowledge Pack that is not on this computer show a passage for this
question once it is installed?

The package carries one signature per cataloged Knowledge Pack in
ai2/data/signatures/, written by tools/build-pack-signatures.py. It holds the
search vectors of the pack, cut to one byte a number. With the question vector a
search already computed and the tally of what the installed parts scored
against it, the standing the best part of such a pack would have beside the
installed ones can be worked out here. Nothing is downloaded and no search
model is asked again.

A signature file, format 1:
  line 1   JSON, UTF-8, ending in a newline, with the keys
           format, id, revision, pack_sha256, model, dims, count, body_sha256
  then     count little-endian float32, the length of each stored vector
  then     count x dims signed bytes, documents by name, parts in order

Standard library only, plain Python. The scan is the whole cost, 768 bytes
for each part of every Knowledge Pack that could be named, so the one loop in
tally() is written for speed.
"""
from __future__ import annotations

import array
import importlib.resources
import json
import math
import operator
import sys

from .doc import STANDING_MIN_PARTS

SIG_DIR = importlib.resources.files("ai2").joinpath("data/signatures")
SIG_FORMAT = 1
SUFFIX = ".sig"
# The first line of a real file is under 300 bytes.
_HEADER_MAX = 4096
# A standing worked out from a signature is not exactly the one the chat gives
# the passage after the install, because a signature keeps one byte a number.
# Measured on 2026-11-23 over the 16 cataloged Knowledge Packs and the 538
# questions of the design set, in three setups of installed Knowledge Packs,
# the two differed by at most 0.00291, 0.00291 and 0.00300 (0.0029983 before
# rounding). Without a margin, 2 of the 172 Knowledge Packs named in the
# third setup showed no passage once installed. One stood at 0.4501 from its
# signature and at 0.4496 installed, under a line of 0.45. recommend() asks
# for this much above the line. With it, 133, 148 and 168 were named in the
# three setups, and none of them stood under the line once installed.
ROUNDING_MARGIN = 0.003
# math.sumprod came with Python 3.12 and halves the time of the scan.
_sumprod = getattr(math, "sumprod", None)


def read(entry: dict, dims: int) -> tuple[array.array, array.array] | None:
    """The signature of a catalog entry for question vectors of `dims`
    numbers: (the length of each stored vector, every vector as signed bytes,
    one after the other). None when there is no file, or when it was not made
    from the pack file this entry names, which shows as another format, id,
    SHA-256, search model, number of dimensions or number of parts, or as a
    length that does not fit. A file that is behind the catalog means silence
    about that Knowledge Pack, never a guess. body_sha256, the SHA-256 of
    everything after line 1, is not looked at here. The package build checks
    it (build-pack-signatures.py --check) and the package is signed."""
    pid = entry.get("id")
    count = entry.get("parts")
    if not isinstance(pid, str) or not pid or "/" in pid or "\\" in pid or pid.startswith("."):
        return None
    if type(count) is not int or count <= 0 or type(dims) is not int or dims <= 0:
        return None
    try:
        raw = SIG_DIR.joinpath(pid + SUFFIX).read_bytes()
    except OSError:
        return None
    cut = raw.find(b"\n", 0, _HEADER_MAX) + 1
    if not cut:
        return None
    try:
        head = json.loads(raw[:cut].decode("utf-8"))
    except ValueError:
        return None
    if not isinstance(head, dict):
        return None
    want = {"format": SIG_FORMAT, "id": pid, "pack_sha256": entry.get("sha256"),
            "model": entry.get("embedder"), "dims": dims, "count": count}
    for key, value in want.items():
        if value is None or type(head.get(key)) is not type(value) or head[key] != value:
            return None
    if len(raw) != cut + 4 * count + dims * count:
        return None
    norms = array.array("f")
    norms.frombytes(raw[cut:cut + 4 * count])
    if sys.byteorder != "little":
        norms.byteswap()
    # a length of zero, or one that is not a number, would break the division
    if not all(0.0 < n < math.inf for n in norms):
        return None
    block = array.array("b")
    block.frombytes(raw[cut + 4 * count:])
    return norms, block


def tally(qvec, norms: array.array, block: array.array, dims: int) -> tuple[float, float, int]:
    """What the parts of a signature score against a question vector: (the
    best score, the sum of all scores, how many). A score is the cosine of the
    question and the stored vector, dot(q, v) / (|q| x |v|), the same number
    doc._scored gives for the part itself, to within what one byte a number
    loses."""
    if len(qvec) != dims or len(block) != dims * len(norms):
        raise ValueError("the question vector and the signature do not have the same dimensions")
    q = tuple(qvec)
    qn = math.sqrt(sum(x * x for x in q)) or 1.0
    best, total, start = -1.0, 0.0, 0
    if _sumprod is not None:
        for norm in norms:
            score = _sumprod(q, block[start:start + dims]) / norm
            start += dims
            total += score
            if score > best:
                best = score
    else:
        mul = operator.mul
        for norm in norms:
            score = sum(map(mul, q, block[start:start + dims])) / norm
            start += dims
            total += score
            if score > best:
                best = score
    return best / qn, total / qn, len(norms)


def recommend(catalog: list[dict], installed_ids: set[str],
              asked: dict[str, tuple[list[float], float, int]], line: float) -> dict | None:
    """The catalog entry of the one Knowledge Pack to name, or None.

    `asked` holds, for every search model a question vector was computed with
    in this search, (the vector, the sum of the scores of the installed parts
    of that model, how many parts that was), which is the tally doc.stand()
    works from. `line` is the standing a passage needs to be shown in the
    chat; the caller passes its own, so there is one line and not two.

    A Knowledge Pack is named only when it is not installed, its search model
    is one of those in `asked` (no vector is ever computed for this), that
    model has enough installed parts for a standing to mean something, and
    the best part of the pack would stand at `line` or higher once its parts
    sat beside the installed ones. The standing is doc.stand()'s, with the
    ordinary score taken over the installed parts and the pack's own. Worked
    out from a signature it must reach `line` + ROUNDING_MARGIN, since the
    real one can be that much lower. Of several the highest wins, and the
    first in the catalog on a tie."""
    # The chat shows a passage at `line`. A signature is rounded, so the pack
    # is named only from ROUNDING_MARGIN above it (see the constant).
    needed = line + ROUNDING_MARGIN
    chosen, chosen_standing = None, None
    for entry in catalog:
        if not isinstance(entry, dict) or entry.get("id") in installed_ids:
            continue
        group = asked.get(entry.get("embedder"))
        if group is None:
            continue
        vector, total, count = group
        if count < STANDING_MIN_PARTS:
            continue
        signature = read(entry, len(vector))
        if signature is None:
            continue
        best, own_total, own_count = tally(vector, *signature, len(vector))
        ordinary = (total + own_total) / (count + own_count)
        if ordinary >= 1.0:
            continue
        standing = (best - ordinary) / (1.0 - ordinary)
        if standing >= needed and (chosen_standing is None or standing > chosen_standing):
            chosen, chosen_standing = entry, standing
    return chosen
