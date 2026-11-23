"""ai2/packsig.py tells from its signature whether a Knowledge Pack from the
catalog that is not on the computer would show a passage for a question."""
import array
import json
import math

import pytest

from ai2 import doc, pack, packsig

V15 = "nomic-embed-text-v1.5"
V2 = "nomic-embed-text-v2-moe"
LINE = 0.45
KEYS = ("burn", "bandage", "fever", "water", "filter", "boil", "x", "y")


def vec(text):
    return [1.0 if k in text.lower() else 0.05 for k in KEYS]


def cosine(a, b):
    return sum(x * y for x, y in zip(a, b)) / math.sqrt(sum(x * x for x in a) * sum(y * y for y in b))


def entry(pid, texts, model=V15):
    return {"id": pid, "title": pid.title(), "revision": 1, "sha256": (pid[0] * 64)[:64], "embedder": model,
            "parts": len(texts)}


def write_sig(folder, e, texts, dims=8, **head):
    """A signature file as tools/build-pack-signatures.py writes one."""
    vectors = []
    for t in texts:
        v = vec(t)[:dims]
        length = math.sqrt(sum(x * x for x in v))
        vectors.append([x / length for x in v])
    scale = max(abs(x) for v in vectors for x in v)
    ints = [array.array("b", (int(round(x / scale * 127)) for x in v)) for v in vectors]
    norms = array.array("f", (math.sqrt(sum(x * x for x in v)) for v in ints))
    line = {"format": 1, "id": e["id"], "revision": e["revision"], "pack_sha256": e["sha256"],
            "model": e["embedder"], "dims": dims, "count": len(ints), **head}
    data = json.dumps(line, separators=(",", ":")).encode() + b"\n" + norms.tobytes() + b"".join(
        v.tobytes() for v in ints)
    (folder / (e["id"] + ".sig")).write_bytes(data)
    return data


@pytest.fixture
def sigs(tmp_path, monkeypatch):
    monkeypatch.setattr(packsig, "SIG_DIR", tmp_path)
    return tmp_path


FIRST_AID = ["burn", "bandage", "fever", "burn bandage"]
WATER = ["water", "filter", "boil water", "filter boil"]


def installed(question, count=100, ordinary=0.2):
    """What a search hands over for one search model, which is the question
    vector and the tally of `count` installed parts that scored `ordinary` on
    average."""
    return (vec(question), ordinary * count, count)


def test_a_signature_is_read_only_when_it_matches_the_catalog_entry(sigs):
    """The file is pinned to the pack file it was made from. A catalog entry
    that has moved on (another revision has another SHA-256 and often another
    number of parts), another search model, a question vector of another size
    or a damaged file all mean nothing is said about that Knowledge Pack."""
    e = entry("first-aid", FIRST_AID)
    whole = write_sig(sigs, e, FIRST_AID)
    norms, block = packsig.read(e, 8)
    assert len(norms) == 4 and len(block) == 32 and block.typecode == "b" and norms.typecode == "f"
    assert max(block) == 127
    for change in ({"sha256": "0" * 64}, {"parts": 5}, {"parts": 3}, {"embedder": V2}, {"id": "other"},
                   {"parts": 0}, {"parts": "4"}, {"sha256": None}, {"id": "../first-aid"}):
        assert packsig.read(dict(e, **change), 8) is None, change
    assert packsig.read(e, 16) is None and packsig.read(e, 4) is None
    path = sigs / "first-aid.sig"
    for damaged in (whole[:-1], whole + b"\0", whole[:20], b"", b"\n" + whole, whole.replace(b'"format":1', b'"format":2')):
        path.write_bytes(damaged)
        assert packsig.read(e, 8) is None, damaged[:30]
    cut = whole.index(b"\n") + 1
    for bad in (0.0, float("nan"), float("inf"), -1.0):
        path.write_bytes(whole[:cut] + array.array("f", [bad]).tobytes() + whole[cut + 4:])
        assert packsig.read(e, 8) is None, bad
    write_sig(sigs, e, FIRST_AID, format=2)
    assert packsig.read(e, 8) is None
    write_sig(sigs, e, FIRST_AID, count=True)
    assert packsig.read(dict(e, parts=1), 8) is None
    path.unlink()
    assert packsig.read(e, 8) is None
    write_sig(sigs, e, FIRST_AID)
    assert packsig.read(e, 8) is not None


def test_the_first_line_alone_is_enough_to_refuse_a_signature(sigs):
    """A file whose name and length fit is still refused when its first line
    names another Knowledge Pack, another number of dimensions or another
    number of parts than the catalog entry and the question vector do."""
    e = entry("first-aid", FIRST_AID)
    whole = write_sig(sigs, e, FIRST_AID)
    cut = whole.index(b"\n") + 1
    head = json.loads(whole[:cut])
    path = sigs / "first-aid.sig"
    for change in ({"id": "other"}, {"dims": 4}, {"dims": 16}, {"count": 1}, {"count": 5},
                   {"dims": 8.0}, {"count": "4"}):
        line = json.dumps(dict(head, **change), separators=(",", ":")).encode() + b"\n"
        path.write_bytes(line + whole[cut:])
        assert packsig.read(e, 8) is None, change
    path.write_bytes(json.dumps(head, separators=(",", ":")).encode() + b"\n" + whole[cut:])
    assert packsig.read(e, 8) is not None


def test_the_shipped_signatures_are_the_ones_this_reads():
    """What the tool writes is what the chat reads. Every cataloged Knowledge
    Pack has a signature that passes, for the 768 numbers both search models
    give."""
    for e in pack.load_catalog():
        norms, block = packsig.read(e, 768)
        assert len(norms) == e["parts"] and len(block) == 768 * e["parts"], e["id"]


@pytest.mark.parametrize("plain", [False, True])
def test_scores_are_the_cosines_of_the_stored_vectors(sigs, monkeypatch, plain):
    """One byte a number moves a score by less than 0.01, and the length of
    the question vector does not matter. Without math.sumprod (Python 3.11)
    the result is the same."""
    if plain:
        monkeypatch.setattr(packsig, "_sumprod", None)
    texts = FIRST_AID + WATER + ["x y", "burn water x"]
    e = entry("mixed", texts)
    write_sig(sigs, e, texts)
    norms, block = packsig.read(e, 8)
    for question in ("burn", "boil water", "fever filter y", "nothing here"):
        want = [cosine(vec(question), vec(t)) for t in texts]
        for q in (vec(question), [7.5 * x for x in vec(question)], tuple(vec(question)), array.array("f", vec(question))):
            best, total, count = packsig.tally(q, norms, block, 8)
            assert count == len(texts)
            assert abs(best - max(want)) < 0.01 and abs(total - sum(want)) < 0.01 * len(texts), question
    best, total, count = packsig.tally(vec("burn"), norms, block, 8)
    assert best > 0.99 and total / count < 0.6
    with pytest.raises(ValueError):
        packsig.tally(vec("burn")[:4], norms, block, 8)
    with pytest.raises(ValueError):
        packsig.tally(vec("burn"), norms, block, 4)


def test_a_pack_that_would_stand_at_the_chat_line_is_recommended(sigs):
    """The installed Knowledge Packs said nothing, and a part of First Aid
    answers to the question far above what an ordinary part does. The
    standing is doc.stand()'s, over the installed parts and the pack's own."""
    catalog = [entry("first-aid", FIRST_AID), entry("water", WATER)]
    for e, texts in zip(catalog, (FIRST_AID, WATER)):
        write_sig(sigs, e, texts)
    asked = {V15: installed("burn")}
    assert packsig.recommend(catalog, {"everyday"}, asked, LINE) is catalog[0]
    assert packsig.recommend(catalog, set(), {V15: installed("boil water")}, LINE) is catalog[1]
    # the same number doc.stand() would give the best part beside the others
    scores = [cosine(vec("burn"), vec(t)) for t in FIRST_AID]
    hit = doc.stand([{"score": max(scores)}], [0.2 * 100 + sum(scores), 100 + len(scores)])[0]
    assert hit["standing"] >= LINE
    just_under = hit["standing"] + 0.02
    assert packsig.recommend(catalog[:1], set(), asked, just_under) is None
    assert packsig.recommend(catalog[:1], set(), asked, hit["standing"] - 0.02) is catalog[0]


def write_bytes_sig(folder, e, rows):
    """A signature whose stored vectors are exactly `rows`, so every score
    is a number that can be written down."""
    ints = [array.array("b", row) for row in rows]
    norms = array.array("f", (math.sqrt(sum(x * x for x in v)) for v in ints))
    line = {"format": 1, "id": e["id"], "revision": e["revision"], "pack_sha256": e["sha256"],
            "model": e["embedder"], "dims": len(rows[0]), "count": len(ints)}
    (folder / (e["id"] + ".sig")).write_bytes(
        json.dumps(line, separators=(",", ":")).encode() + b"\n" + norms.tobytes() + b"".join(v.tobytes() for v in ints))


def test_the_standing_counts_the_packs_own_parts_among_the_ordinary(sigs):
    """Once installed, the parts of the pack sit beside the others, so the
    ordinary score doc.stand() takes is over the installed parts and the
    pack's own. Two parts scoring 0.6 and 0.8 beside 50 installed ones that
    averaged 0.1 stand at 0.772. Left out of the ordinary score they would
    seem to stand at 0.778."""
    e = entry("edge", ["a", "b"])
    write_bytes_sig(sigs, e, [[127, 0], [0, 127]])
    question = [3.0, 4.0]                                       # cosines 0.6 and 0.8
    assert packsig.tally(question, *packsig.read(e, 2), 2) == pytest.approx((0.8, 1.4, 2), abs=1e-12)
    ordinary = (5.0 + 0.6 + 0.8) / (50 + 2)
    standing = (0.8 - ordinary) / (1.0 - ordinary)
    assert standing == pytest.approx(0.77193, abs=1e-5)
    assert doc.stand([{"score": 0.8}], [5.0 + 1.4, 52])[0]["standing"] == pytest.approx(standing, abs=1e-12)
    asked = {V15: ([3.0, 4.0], 5.0, 50)}
    line = standing - packsig.ROUNDING_MARGIN         # the standing has to clear the line by the margin
    assert packsig.recommend([e], set(), asked, line - 1e-9) is e
    assert packsig.recommend([e], set(), asked, line + 1e-9) is None


def test_a_standing_must_clear_the_line_by_the_rounding_margin(sigs):
    """The chat shows a passage whose standing is CHAT_MATCH or higher. A
    signature keeps one byte a number, which moves a standing by up to 0.003,
    so a Knowledge Pack is named only when its standing from the signature is
    the line plus that margin or higher. Exactly there is enough, and a hair
    under is not."""
    assert packsig.ROUNDING_MARGIN == 0.003
    e = entry("edge", ["a"])
    write_bytes_sig(sigs, e, [[127, 0]])
    # best 1, ordinary (0 + 1) / (99 + 1), standing (1 - 0.01) / (1 - 0.01), which is 1
    asked = {V15: ([1.0, 0.0], 0.0, 99)}
    assert 0.997 + 0.003 == 1.0                       # these two add up without a rounding error
    assert packsig.recommend([e], set(), asked, 0.997) is e
    assert packsig.recommend([e], set(), asked, 0.997 + 1e-12) is None
    # without the margin the next two would be named, and with twice the margin 0.997 would not
    assert packsig.recommend([e], set(), asked, 0.9971) is None
    assert packsig.recommend([e], set(), asked, 1.0) is None
    assert packsig.recommend([e], set(), asked, 0.9969) is e


def test_a_pack_under_the_line_is_not(sigs):
    """A question none of its parts is about, and a question the installed
    parts already score high on, which leaves no room to rise."""
    catalog = [entry("first-aid", FIRST_AID)]
    write_sig(sigs, catalog[0], FIRST_AID)
    assert packsig.recommend(catalog, set(), {V15: installed("x y")}, LINE) is None
    assert packsig.recommend(catalog, set(), {V15: installed("water filter")}, LINE) is None
    assert packsig.recommend(catalog, set(), {V15: installed("burn fever", ordinary=0.6)}, LINE) is None
    assert packsig.recommend(catalog, set(), {V15: installed("burn fever")}, LINE) is catalog[0]
    # as in doc.stand(), an ordinary score of 1 or more gives no standing at all
    assert packsig.recommend(catalog, set(), {V15: installed("burn fever", ordinary=2.0)}, LINE) is None


def test_installed_packs_and_models_without_a_question_vector_are_skipped(sigs, monkeypatch):
    """Nothing is named that is already here, and no vector is computed for
    this. A Knowledge Pack built with a search model the search did not use
    is passed over without its file being opened. One whose file is missing
    or behind the catalog is passed over too."""
    catalog = [entry("first-aid", FIRST_AID), entry("primeros-auxilios", FIRST_AID, model=V2)]
    for e in catalog:
        write_sig(sigs, e, FIRST_AID)
    asked = {V15: installed("burn")}
    assert packsig.recommend(catalog, {"first-aid"}, asked, LINE) is None
    assert packsig.recommend(catalog, set(), asked, LINE) is catalog[0]
    both = dict(asked, **{V2: installed("burn")})
    assert packsig.recommend(catalog, {"first-aid"}, both, LINE) is catalog[1]
    assert packsig.recommend(catalog, {"first-aid"}, {}, LINE) is None
    opened = []
    real = packsig.read
    monkeypatch.setattr(packsig, "read", lambda e, dims: opened.append(e["id"]) or real(e, dims))
    assert packsig.recommend(catalog, {"first-aid"}, asked, LINE) is None and opened == []
    assert packsig.recommend(catalog, set(), asked, LINE) is catalog[0] and opened == ["first-aid"]
    moved_on = [dict(catalog[0], sha256="e" * 64, revision=2)]
    assert packsig.recommend(moved_on, set(), asked, LINE) is None
    (sigs / "first-aid.sig").unlink()
    assert packsig.recommend(catalog, set(), asked, LINE) is None
    assert packsig.recommend([], set(), asked, LINE) is None


def test_only_the_best_of_two_is_named(sigs):
    """One Knowledge Pack at most. Of two that would both show a passage the
    one standing higher is named, wherever it sits in the catalog, and of two
    that stand the same the first in the catalog."""
    exact, near = ["burn bandage", "fever"], ["burn", "fever"]
    a, b = entry("near", near), entry("exact", exact)
    write_sig(sigs, a, near)
    write_sig(sigs, b, exact)
    asked = {V15: installed("burn bandage")}
    assert packsig.recommend([a], set(), asked, LINE) is a
    assert packsig.recommend([a, b], set(), asked, LINE) is b
    assert packsig.recommend([b, a], set(), asked, LINE) is b
    twin = entry("twin", exact)
    write_sig(sigs, twin, exact)
    assert packsig.recommend([b, twin], set(), asked, LINE) is b
    assert packsig.recommend([twin, b], set(), asked, LINE) is twin


def test_a_group_with_too_few_installed_parts_gets_nothing(sigs):
    """Under doc.STANDING_MIN_PARTS installed parts of a search model the chat
    gives no standing, so it would not show the passage after the install
    either, and nothing is named."""
    catalog = [entry("first-aid", FIRST_AID)]
    write_sig(sigs, catalog[0], FIRST_AID)
    few = doc.STANDING_MIN_PARTS - 1
    assert packsig.recommend(catalog, set(), {V15: installed("burn", count=few)}, LINE) is None
    assert packsig.recommend(catalog, set(), {V15: installed("burn", count=few + 1)}, LINE) is catalog[0]
    assert packsig.recommend(catalog, set(), {V15: installed("burn", count=0, ordinary=0.0)}, LINE) is None
