from ai2 import doctor
from ai2.detect import Hardware
from tests.test_tuning import FakeBackend


def test_render_and_verdict():
    checks = [doctor.Check(doctor.OK, "A", "fine"), doctor.Check(doctor.WARN, "B", "meh")]
    assert doctor.verdict(checks) == 1
    checks.append(doctor.Check(doctor.FAIL, "C", "broken"))
    assert doctor.verdict(checks) == 2
    text = doctor.render(checks)
    assert "WARN  B" in text and "FAIL  C" in text


def test_service_check_against_expectation():
    b = FakeBackend(enabled={"earlyoom", "cupsd"}, unknown={"avahi-daemon"})
    assert doctor.check_service(b, "earlyoom", True).status == doctor.OK
    assert doctor.check_service(b, "cupsd", False).status == doctor.WARN
    assert doctor.check_service(b, "avahi-daemon", False).status == doctor.INFO


def test_runtime_check_names_the_package(monkeypatch):
    monkeypatch.setattr(doctor, "find_runtime", lambda v: None)
    hw = Hardware(flags=set())
    c = doctor.check_runtime(hw)
    assert c.status == doctor.FAIL and "ai2-llama-cpp" in c.detail


def test_report_has_no_home_path(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    hw = Hardware(cpu_model="test cpu", logical_cores=2, ram_mib=3000, ram_nominal_gib=4, flags=set())
    text = doctor.report_text(hw, [doctor.Check(doctor.OK, "A", "fine")])
    assert "== Hardware" in text and "test cpu" in text
    assert str(tmp_path) not in text


def test_update_check_does_not_call_a_failed_check_current(tmp_path, monkeypatch):
    """A failed check (the checker exits with an error) is "unknown", not
    "system is current", and the hint is ai-2 update."""
    from tests.test_updates import _fake_checkupdates
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\nexit 1\n")
    c = doctor.check_updates()
    assert "could not check" in c.detail and "current" not in c.detail
    _fake_checkupdates(tmp_path, monkeypatch, "#!/bin/sh\necho 'a  1-1 -> 1-2'\necho 'b  1-1 -> 1-2'\nexit 100\n")
    c = doctor.check_updates()
    assert c.detail.startswith("2 package update(s)") and "ai-2 update" in c.detail
    assert "pacman -Syu" not in c.detail


def test_doctor_looks_at_the_packs_and_the_model_they_need(monkeypatch):
    """A machine whose packs cannot be searched at all used to report OK."""
    from ai2 import doc, pack, packbrowse
    manifest = {"id": "ai2-help", "title": "AI-2 Help",
                "embedder": {"id": "nomic-embed-text-v1.5"}}
    monkeypatch.setattr(pack, "installed_packs", lambda: [("ai2-help", manifest)])
    monkeypatch.setattr(pack, "manifest_of", lambda name: manifest if name == "ai2-help" else None)
    monkeypatch.setattr(doc, "list_collections", lambda: ["ai2-help", "documents"])
    monkeypatch.setattr(doc, "store_model", lambda conn: "nomic-embed-text-v2-moe")
    from types import SimpleNamespace
    monkeypatch.setattr(doc, "open_store_readonly", lambda path: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(packbrowse, "outdated", lambda: [{"id": "ai2-help", "title": "AI-2 Help"}])

    monkeypatch.setattr(doctor, "find_model_file", lambda f: None)
    checks = {c.name: c for c in doctor.check_knowledge()}
    assert checks["Knowledge Packs"].detail.startswith("1 installed: AI-2 Help")
    assert checks["Pack embedder"].status == doctor.WARN and "not downloaded" in checks["Pack embedder"].detail
    assert "another embedding model" in checks["Your documents"].detail
    assert checks["Pack updates"].status == doctor.WARN and "ai-2 knowledge update" in checks["Pack updates"].detail

    monkeypatch.setattr(doctor, "find_model_file", lambda f: "/models/" + f)
    assert {c.name: c for c in doctor.check_knowledge()}["Pack embedder"].status == doctor.OK


def test_doctor_says_when_there_are_no_packs(monkeypatch):
    from ai2 import pack
    monkeypatch.setattr(pack, "installed_packs", lambda: [])
    only = doctor.check_knowledge()
    assert len(only) == 1 and only[0].status == doctor.INFO and "none installed" in only[0].detail


# The schema of a personal index as ai-2 0.29.5 wrote it (ai2/doc.py at
# v0.29.5), before index_fingerprints, index_checkpoints and checkpoint_parts.
SCHEMA_0295 = """
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS docs (
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT, added TEXT,
        words INTEGER, chunks INTEGER);
    CREATE TABLE IF NOT EXISTS chunks (
        id INTEGER PRIMARY KEY, doc_id INTEGER REFERENCES docs(id) ON DELETE CASCADE,
        ord INTEGER, text TEXT, vec BLOB, page INTEGER, page_end INTEGER);
    CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
"""


def _index_0295(path, model):
    import sqlite3
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_0295)
    conn.execute("INSERT INTO meta VALUES ('model', ?)", (model,))
    conn.execute("INSERT INTO docs VALUES (1, 'notes.txt', '/x/notes.txt', '2026-11-20', 3, 1)")
    conn.execute("INSERT INTO chunks VALUES (1, 1, 0, 'three short words', ?, NULL, NULL)",
                 (b"\x00" * 16,))
    conn.commit()
    conn.close()


def test_doctor_reads_an_older_index_without_changing_it(tmp_path, monkeypatch):
    """`ai-2 doctor` read a personal index's model through a writable open,
    which added the newer tables to an index made by 0.29.5: running the
    diagnostic changed the person's file. It must read it as it is."""
    import hashlib
    import sqlite3
    from ai2 import doc, pack, packbrowse
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("AI2_SYSTEM_DOC_DIR", str(tmp_path / "system"))
    index = tmp_path / "data" / "ai2" / "doc" / "notes" / "index.sqlite"
    _index_0295(index, "nomic-embed-text-v2-moe")
    manifest = {"id": "ai2-help", "title": "AI-2 Help", "embedder": {"id": "nomic-embed-text-v1.5"}}
    monkeypatch.setattr(pack, "installed_packs", lambda: [("ai2-help", manifest)])
    monkeypatch.setattr(pack, "manifest_of", lambda name: manifest if name == "ai2-help" else None)
    monkeypatch.setattr(packbrowse, "outdated", lambda: [])
    monkeypatch.setattr(doctor, "find_model_file", lambda f: "/models/" + f)
    assert doc.list_collections() == ["notes"]

    def snapshot():
        return (hashlib.sha256(index.read_bytes()).hexdigest(), index.stat().st_mtime_ns,
                sorted(p.name for p in index.parent.iterdir()))

    before = snapshot()
    checks = {c.name: c for c in doctor.check_knowledge()}
    # the model was read: v2-moe differs from the pack's v1.5, so doctor says so
    assert "another embedding model" in checks["Your documents"].detail
    assert snapshot() == before, "doctor changed the index"
    conn = sqlite3.connect(index)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    conn.close()
    assert tables == {"meta", "docs", "chunks"}

    # and the same model as the pack's gives no note, so the value itself was read
    index.unlink()
    _index_0295(index, "nomic-embed-text-v1.5")
    before = snapshot()
    assert "Your documents" not in {c.name for c in doctor.check_knowledge()}
    assert snapshot() == before, "doctor changed the index"
