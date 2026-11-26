"""Private collections become visible atomically. Export uses real packs."""
from pathlib import Path

import pytest

from ai2 import doc, pack, packcreator as creator


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "author"))
    monkeypatch.setenv("AI2_SYSTEM_DOC_DIR", str(tmp_path / "system"))

    def index(arguments, *, env, report, started):
        # Provide fixed vectors in place of the running model; keep AI-2's real store and export.
        with monkeypatch.context() as stage:
            stage.setenv("XDG_DATA_HOME", env["XDG_DATA_HOME"])
            assert arguments[:6] == ["doc", "index", "--in", "draft", "--embedder", "nomic-embed-text-v2-moe"]
            conn = doc.open_store(doc.index_path("draft"))
            doc.set_store_model(conn, arguments[5], 2)
            for path in arguments[7:]:
                text = path.read_text()
                doc.add_document(conn, path.name, str(path), [text], [[1., 0.]], len(text.split()))
            conn.close()
    monkeypatch.setattr(creator, "run_cli", index)
    return tmp_path


def test_create_reopen_save_and_install_without_sharing_the_original(local, monkeypatch):
    file = local / "Notes.txt"
    file.write_text("Las habas se siembran en mayo.")
    name, details = creator.create("Mi huerta en Córdoba", "es", [file], "Notas de riego")
    assert name == "mi-huerta-en-cordoba"
    assert creator.private_collections()[name] == details
    assert pack.manifest_of(name) is None and pack.installed_packs() == []
    with doc.open_store_readonly(doc.index_path(name)) as conn:
        notes = conn.execute("SELECT path FROM docs WHERE name != ?", (file.name,)).fetchone()[0]
    assert Path(notes).read_text() == "Notas de riego"
    other, _ = creator.create("Mi huerta en Córdoba", "es", [], "Otras notas")
    assert other != name
    destination = local / "copy.ai2pack"
    creator.save_pack(name, details, destination)
    monkeypatch.setenv("XDG_DATA_HOME", str(local / "friend"))
    installed, manifest, previous = pack.install_pack(str(destination))
    assert installed == name and previous is None
    assert manifest["index"]["documents"] == 2
    assert manifest["languages"] == ["es"] and manifest["license"] == "unspecified"
    with doc.open_store_readonly(doc.index_path(installed)) as conn:
        assert all(Path(path).name == path for path, in conn.execute("SELECT path FROM docs"))


def test_interrupted_index_and_duplicate_names_do_not_change_collections(local, monkeypatch):
    with pytest.raises(ValueError, match="same name"):
        creator.create("Garden", "es", [local / "first/a.txt", local / "second/a.txt"], "")
    def fail(*args, **kwargs):
        raise OSError("interrupted")
    monkeypatch.setattr(creator, "run_cli", fail)
    with pytest.raises(OSError, match="interrupted"):
        creator.create("Garden", "es", [], "notes")
    assert list(Path(doc.doc_root()).iterdir()) == []


def test_language_selection_and_model():
    assert creator.model_for("en-GB")["multilingual"] is False
    assert creator.model_for("es")["multilingual"] is True
    assert creator.valid_language("es-AR") and not creator.valid_language("Español")


def test_window_entry_points(monkeypatch):
    import sys
    from types import SimpleNamespace
    from ai2 import cli
    calls = []
    mock = SimpleNamespace(open_window=lambda create: calls.append(create) or True)
    monkeypatch.setitem(sys.modules, "ai2.packwindow", mock)
    monkeypatch.setattr("ai2.packwindow", mock, raising=False)
    assert cli.main(["knowledge", "create"]) == cli.main(["knowledge", "manage"]) == 0
    assert calls == [True, False]


def test_index_progress_reads_the_indexer_lines():
    state, seen = {}, []
    lines = ["Downloading Nomic (328 MB) to /x/ ...",
             "3/9 parts, 4 s, about 1 min left",                 # before any document: nothing to say
             "guia.txt: 1851 words in 21 parts, indexing with Nomic Embed Text v2 MoE (slow on an old CPU; you can leave it running) ...",
             "4/21 parts, 40 s, about 3 min left",
             "20/21 parts, 200 s, about 1 min left",
             "guia.txt: 21 parts indexed in 210 s",
             "Notes.txt: 7 words in 1 parts, indexing with Nomic Embed Text v2 MoE (slow on an old CPU; you can leave it running) ..."]
    for line in lines:
        info = creator.index_progress(line, state, 2)
        if info:
            seen.append((info["document"], info["documents"], info["name"], info["done"], info["total"],
                         info["minutes"], round(info["fraction"], 3)))
    assert seen == [(1, 2, "guia.txt", 0, 21, None, 0.0), (1, 2, "guia.txt", 4, 21, 3, 0.095),
                    (1, 2, "guia.txt", 20, 21, 1, 0.476), (2, 2, "Notes.txt", 0, 1, None, 0.5)]


def test_create_passes_progress_on(local, monkeypatch):
    def index(arguments, *, env, report, started):
        report("a.txt: 5 words in 2 parts, indexing with X ...")
        report("1/2 parts, 3 s, about 1 min left")
        raise OSError("stop here")
    monkeypatch.setattr(creator, "run_cli", index)
    got, lines = [], []
    with pytest.raises(OSError):
        creator.create("Garden", "es", [], "notes", report=lines.append, progress=got.append)
    assert [(i["done"], i["total"], i["fraction"]) for i in got] == [(0, 2, 0.0), (1, 2, 0.5)]
    assert len(lines) == 2
