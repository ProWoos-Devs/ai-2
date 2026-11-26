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
