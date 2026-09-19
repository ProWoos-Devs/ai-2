"""`ai-2 knowledge`: export a collection, install it elsewhere, and refuse
anything that is not exactly what an export writes."""
import os
import sqlite3
import zipfile

import pytest
import yaml

from ai2 import doc, pack
from ai2.models import embedding_models

V2 = "nomic-embed-text-v2-moe"


def vec(text):
    keys = ("madrid", "castellano", "bandera", "mili", "x", "y", "z", "w")
    return [1.0 if k in text.lower() else 0.05 for k in keys]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return tmp_path


def make_collection(name, docs, model=V2):
    conn = doc.open_store(doc.index_path(name))
    doc.set_store_model(conn, model, 8)
    for doc_name, texts in docs.items():
        doc.add_document(conn, doc_name, f"/home/someone/private/{doc_name}", texts, [vec(t) for t in texts],
                         words=10, pages=[(i + 1, i + 1) for i in range(len(texts))])
    conn.close()


TEMPLATE = {"id": "constitucion-es", "version": "2026-09-16", "title": "Constitución Española",
            "languages": ["es"], "license": "public-domain (LPI art. 13)",
            "attribution": "Basado en datos de la Agencia Estatal Boletín Oficial del Estado, https://www.boe.es",
            "sources": [{"file": "c.pdf", "title": "Constitución Española", "url": "https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229"}]}


def test_export_writes_two_members_and_leaves_paths_out(home):
    make_collection("constitucion", {"c.pdf": ["La capital es Madrid.", "El castellano.", "La bandera."]})
    out = str(home / "c.ai2pack")
    m = pack.export_pack("constitucion", out, TEMPLATE)
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["index.sqlite", "manifest.yml"]
        z.extract("index.sqlite", home / "x")
        stored = yaml.safe_load(z.read("manifest.yml"))
    assert stored == m and m["id"] == "constitucion-es" and m["format"] == 1
    assert m["embedder"]["id"] == V2 and len(m["embedder"]["sha256"]) == 64
    assert m["index"]["documents"] == 1 and m["index"]["parts"] == 3
    assert m["index"]["sha256"] == pack.sha256_file(str(home / "x" / "index.sqlite"))
    paths = [r[0] for r in sqlite3.connect(home / "x" / "index.sqlite").execute("SELECT path FROM docs")]
    assert paths == ["c.pdf"]                                    # not /home/someone/private/c.pdf
    # the collection itself is untouched
    assert doc.list_documents(doc.open_store(doc.index_path("constitucion")))[0]["path"].startswith("/home/someone")
    with pytest.raises(pack.PackError, match="unknown manifest keys: secret"):
        pack.export_pack("constitucion", out, {"secret": 1})
    with pytest.raises(pack.PackError, match="no collection"):
        pack.export_pack("ghost", out)


def test_install_roundtrip_update_and_name_clashes(home):
    make_collection("constitucion", {"c.pdf": ["La capital es Madrid.", "El castellano."]})
    out = str(home / "c.ai2pack")
    pack.export_pack("constitucion", out, TEMPLATE)
    name, m, previous = pack.install_pack(out)
    assert (name, previous) == ("constitucion-es", None)
    assert "constitucion-es" in doc.list_collections()
    assert pack.manifest_of("constitucion-es")["title"] == "Constitución Española"
    assert pack.manifest_of("constitucion") is None                  # one's own collection
    hits = doc.search(doc.open_store(doc.index_path("constitucion-es")), vec("Madrid"), top=1)
    assert hits[0]["page"] == 1 and hits[0]["doc"] == "c.pdf"
    assert pack.source_url(m, "c.pdf").startswith("https://www.boe.es/")
    # a newer version of the same pack replaces it
    pack.export_pack("constitucion", out, dict(TEMPLATE, version="2026-10-01"))
    name, m2, previous = pack.install_pack(out)
    assert previous["version"] == "2026-09-16" and pack.manifest_of(name)["version"] == "2026-10-01"
    assert not [n for n in os.listdir(doc.doc_root()) if n.startswith(".")]   # no staging left behind
    # never over a collection of one's own, --as gives another name
    with pytest.raises(pack.PackError, match="already exists and is not this pack"):
        pack.install_pack(out, name="constitucion")
    assert pack.install_pack(out, name="copia")[0] == "copia"
    with pytest.raises(pack.PackError, match="not a collection name"):
        pack.install_pack(out, name="../evil")


def _rewrite(src, dst, manifest=None, index_bytes=None, extra=None):
    with zipfile.ZipFile(src) as z:
        m = yaml.safe_load(z.read("manifest.yml"))
        idx = z.read("index.sqlite")
    with zipfile.ZipFile(dst, "w") as z:
        z.writestr("manifest.yml", yaml.safe_dump(manifest(m) if manifest else m))
        z.writestr("index.sqlite", index_bytes if index_bytes is not None else idx)
        for name, data in (extra or {}).items():
            z.writestr(name, data)


def test_install_refuses_what_an_export_would_not_write(home):
    make_collection("c", {"c.pdf": ["La capital es Madrid."]})
    good = str(home / "good.ai2pack")
    pack.export_pack("c", good, TEMPLATE)
    bad = str(home / "bad.ai2pack")
    cases = [
        (dict(extra={"../../etc/evil": b"x"}), "not an AI-2 pack"),
        (dict(manifest=lambda m: dict(m, format=2)), "format 2"),
        (dict(manifest=lambda m: dict(m, id="../x")), "not a valid collection name"),
        (dict(manifest=lambda m: dict(m, embedder={"id": "all-MiniLM-L6-v2", "sha256": "0" * 64})), "not in this AI-2's catalog"),
        (dict(manifest=lambda m: dict(m, embedder={"id": V2, "sha256": "0" * 64})), "different file"),
        (dict(index_bytes=b"not sqlite at all"), "does not match its manifest"),
    ]
    for kwargs, message in cases:
        _rewrite(good, bad, **kwargs)
        with pytest.raises(pack.PackError, match=message):
            pack.install_pack(bad)
    with open(str(home / "junk.ai2pack"), "wb") as fh:
        fh.write(b"PK nothing")
    with pytest.raises(pack.PackError, match="not an AI-2 pack"):
        pack.install_pack(str(home / "junk.ai2pack"))
    assert doc.list_collections() == ["c"]
    assert not [n for n in os.listdir(doc.doc_root()) if n.startswith(".")]


def test_untrusted_open_turns_defensive_on(home):
    """https://www.sqlite.org/security.html wants DEFENSIVE on for a file
    someone else wrote. The other three switches stay off. Python before 3.12
    has no setconfig; the PRAGMAs and the schema allowlist still run."""
    if not hasattr(sqlite3.Connection, "setconfig"):
        pytest.skip("setconfig needs Python 3.12+")
    make_collection("c", {"c.pdf": ["La capital es Madrid."]})
    path = doc.index_path("c")
    conn = pack._open_untrusted(path)
    try:
        assert conn.getconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE) is True
        assert conn.getconfig(sqlite3.SQLITE_DBCONFIG_TRUSTED_SCHEMA) is False
        assert conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_TRIGGER) is False
        assert conn.getconfig(sqlite3.SQLITE_DBCONFIG_ENABLE_VIEW) is False
    finally:
        conn.close()


def test_install_refuses_a_hostile_or_inconsistent_index(home):
    """A matching sha256 only proves the manifest and index travel together:
    whoever wrote one wrote both. The index itself is checked."""
    make_collection("c", {"c.pdf": ["La capital es Madrid.", "Otra parte."]})
    good = str(home / "good.ai2pack")
    pack.export_pack("c", good, TEMPLATE)
    with zipfile.ZipFile(good) as z:
        z.extract("index.sqlite", home / "src")
    src = str(home / "src" / "index.sqlite")

    def variant(sql, manifest_edit=None):
        path = str(home / "v.sqlite")
        if os.path.exists(path):
            os.remove(path)
        import shutil
        shutil.copy(src, path)
        conn = sqlite3.connect(path)
        conn.executescript(sql)
        conn.commit()
        conn.close()
        data = open(path, "rb").read()
        sha = pack.hashlib.sha256(data).hexdigest()
        _rewrite(good, str(home / "v.ai2pack"), index_bytes=data,
                 manifest=lambda m: (manifest_edit or (lambda x: x))(dict(m, index=dict(m["index"], sha256=sha))))
        return str(home / "v.ai2pack")

    trigger = "CREATE TRIGGER t AFTER INSERT ON docs BEGIN DELETE FROM chunks; END;"
    with pytest.raises(pack.PackError, match="unexpected schema.*trigger t"):
        pack.install_pack(variant(trigger))
    with pytest.raises(pack.PackError, match="unexpected schema.*view v"):
        pack.install_pack(variant("CREATE VIEW v AS SELECT * FROM docs;"))
    with pytest.raises(pack.PackError, match="different embedding models"):
        pack.install_pack(variant(f"UPDATE meta SET value = 'nomic-embed-text-v1.5' WHERE key = 'model';"))
    with pytest.raises(pack.PackError, match="documents and parts"):
        pack.install_pack(variant("DELETE FROM chunks WHERE ord = 1;"))
    assert doc.list_collections() == ["c"]


def test_knowledge_remove_takes_the_catalog_id_of_a_renamed_pack(home, monkeypatch, capsys):
    """`install --as` puts a pack under another collection name, while every
    list and the Knowledge Packs window keep showing the catalog id."""
    from ai2 import cli
    make_collection("constitucion", {"c.pdf": ["Artículo 30."]})
    tpl = home / "manifest.yml"
    tpl.write_text(yaml.safe_dump(TEMPLATE, allow_unicode=True), encoding="utf-8")
    out = str(home / "out.ai2pack")
    assert cli.main(["knowledge", "export", "constitucion", "-o", out, "--manifest", str(tpl)]) == 0
    cli.main(["doc", "forget", "--all", "--in", "constitucion"])
    assert cli.main(["knowledge", "install", out, "--as", "leyes"]) == 0
    capsys.readouterr()
    assert cli.main(["knowledge", "remove", "constitucion-es"]) == 0
    assert "was installed as leyes" in capsys.readouterr().out
    assert doc.list_collections() == []


def test_knowledge_cli_export_install_search_list_remove(home, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setattr(cli, "_ensure_server", lambda hw, model, port, record, **kw: "http://127.0.0.1:8081/")
    monkeypatch.setattr(cli, "find_model_file", lambda f: "/m/" + f)
    monkeypatch.setattr(doc.EmbedClient, "embed_query", lambda self, q: vec(q))
    monkeypatch.setattr(doc, "choose_embedder", lambda ram, catalog=None: {"id": V2})
    make_collection("constitucion", {"c.pdf": ["Artículo 30. servicio militar, la mili.", "La bandera."]})
    tpl = home / "manifest.yml"
    tpl.write_text(yaml.safe_dump(TEMPLATE, allow_unicode=True), encoding="utf-8")
    out = str(home / "out.ai2pack")
    assert cli.main(["knowledge", "export", "constitucion", "-o", out, "--manifest", str(tpl)]) == 0
    assert "Document paths on this computer are not included" in capsys.readouterr().out
    cli.main(["doc", "forget", "--all", "--in", "constitucion"])
    capsys.readouterr()
    assert cli.main(["knowledge", "install", out]) == 0
    text = capsys.readouterr().out
    assert "Installed constitucion-es, Constitución Española version 2026-09-16" in text
    assert "Basado en datos de la Agencia Estatal" in text and "--in constitucion-es" in text
    assert cli.main(["doc", "search", "--top", "1", "¿Tengo que hacer la mili?"]) == 0
    text = capsys.readouterr().out
    assert "[1] c.pdf, page 1  https://www.boe.es/buscar/act.php?id=BOE-A-1978-31229" in text
    assert "From the pack Constitución Española (public-domain (LPI art. 13)). Basado en datos" in " ".join(text.split())
    assert cli.main(["doc", "list"]) == 0
    assert "pack Constitución Española, version 2026-09-16" in capsys.readouterr().out
    assert cli.main(["knowledge", "list"]) == 0
    assert "constitucion-es" in capsys.readouterr().out
    make_collection("mine", {"n.txt": ["nota"]})
    assert cli.main(["knowledge", "remove", "mine"]) == 1
    assert "not an installed knowledge pack" in capsys.readouterr().err
    assert cli.main(["knowledge", "remove", "constitucion-es"]) == 0
    assert doc.list_collections() == ["mine"]
    assert cli.main(["knowledge", "install", str(home / "missing.ai2pack")]) == 1
    assert "no pack file at" in capsys.readouterr().err
    assert cli.main(["knowledge", "list"]) == 0
    assert "No knowledge packs installed" in capsys.readouterr().out


def _serve(directory):
    """A localhost HTTP server over `directory`, returned with its base URL."""
    import functools
    import threading
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_port}"


def test_install_by_name_from_the_catalog(home, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setattr(cli, "find_model_file", lambda f: "/m/" + f)
    make_collection("src", {"c.pdf": ["La capital es Madrid.", "El castellano."]})
    packs = home / "served"
    packs.mkdir()
    out = str(packs / "everyday.ai2pack")
    m = pack.export_pack("src", out, dict(TEMPLATE, id="everyday", title="Everyday Reference",
                                          license="CC0-1.0", attribution=""))
    httpd, base = _serve(packs)
    entry = {"id": "everyday", "title": "Everyday Reference", "version": m["version"], "languages": ["en"],
             "license": "CC0-1.0", "embedder": V2, "url": base + "/everyday.ai2pack",
             "size_bytes": os.path.getsize(out), "sha256": pack.sha256_file(out),
             "documents": 1, "parts": 2}
    monkeypatch.setattr(pack, "load_catalog", lambda: [entry])
    try:
        assert cli.main(["knowledge", "available"]) == 0
        text = capsys.readouterr().out
        assert "everyday" in text and "Everyday Reference" in text and "CC0-1.0" in text
        # only the signed list is fetched by name, and the listing says where
        # the packs other people have made are to be found instead
        assert "ai2-knowledge" in text and "install FILE.ai2pack" in text
        assert cli.main(["knowledge", "available", "nothing-like-this"]) == 0
        assert "No knowledge packs to fetch by name yet" in capsys.readouterr().out
        assert cli.main(["knowledge", "install", "everyday"]) == 0
        text = capsys.readouterr().out
        assert "Downloading" in text and "Installed everyday" in text
        assert pack.manifest_of("everyday")["title"] == "Everyday Reference"
        assert cli.main(["knowledge", "available"]) == 0
        assert "[installed]" in capsys.readouterr().out
        # a wrong hash in the catalog stops the install and leaves nothing behind
        pack.remove_pack_collection = getattr(pack, "remove_pack_collection", None)
        doc.remove_collection("everyday")
        entry["sha256"] = "0" * 64
        assert cli.main(["knowledge", "install", "everyday"]) == 1
        assert "checksum mismatch" in capsys.readouterr().err
        assert "everyday" not in doc.list_collections()
        assert not [f for f in os.listdir(doc.data_dir() + "/packs") if f.endswith(".part")]
    finally:
        httpd.shutdown()


def test_the_shipped_catalog_is_usable():
    """Every entry AI-2 ships must be complete enough to fetch and to show,
    and its licence must be one that allows redistribution (the same rule the
    ai2-knowledge repository applies to contributed packs)."""
    import re
    allowed = {"CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-SA-3.0", "CC-BY-SA-2.5", "CC-BY-3.0",
               "MIT", "Apache-2.0", "GFDL-1.3-or-later", "public-domain", "PSF-2.0", "OGL-3.0"}
    ids = set()
    for e in pack.load_catalog():
        for field in ("id", "title", "version", "languages", "license", "embedder", "url",
                      "size_bytes", "sha256", "documents", "parts"):
            assert e.get(field) not in (None, "", []), f"{e.get('id')}: {field} missing"
        assert doc.valid_collection(e["id"]) and e["id"] not in ids
        ids.add(e["id"])
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), f"{e['id']}: sha256"
        assert e["url"].startswith("https://"), f"{e['id']}: url must be https"
        assert e["license"] in allowed, f"{e['id']}: licence {e['license']}"
        assert e["embedder"] in {m["id"] for m in embedding_models()}, f"{e['id']}: unknown embedder"
        if e["license"].startswith(("CC-BY", "GFDL", "PSF", "OGL")):
            assert str(e.get("attribution", "")).strip(), f"{e['id']}: needs an attribution line"


def test_a_pack_cannot_be_put_back_to_an_older_revision(home):
    """`version` is for people and cannot be ordered reliably, so the code
    orders by `revision`. A file from another route must not quietly undo an
    update; --force is the way to say you mean it."""
    make_collection("src", {"c.pdf": ["La capital es Madrid."]})
    old = str(home / "old.ai2pack")
    new = str(home / "new.ai2pack")
    pack.export_pack("src", old, dict(TEMPLATE, id="everyday", version="2026-08-01", revision=1))
    pack.export_pack("src", new, dict(TEMPLATE, id="everyday", version="2026-09-16", revision=2))
    assert pack.install_pack(old)[0] == "everyday"
    assert pack.revision_of(pack.manifest_of("everyday")) == 1
    # a higher revision updates
    name, m, previous = pack.install_pack(new)
    assert pack.revision_of(m) == 2 and previous["version"] == "2026-08-01"
    # the same revision is allowed (a reinstall of the same pack)
    assert pack.install_pack(new)[2]["version"] == "2026-09-16"
    # an older one is refused, and the installed pack is untouched
    with pytest.raises(pack.PackError, match="which is older; install it anyway with --force"):
        pack.install_pack(old)
    assert pack.manifest_of("everyday")["version"] == "2026-09-16"
    assert pack.install_pack(old, force=True)[1]["version"] == "2026-08-01"
    # a manifest with no revision counts as 1, and a bad one is refused
    assert pack.revision_of({"id": "x"}) == 1
    assert any("revision" in p for p in pack.check_manifest(dict(pack.read_manifest(new), revision=0)))
    assert any("revision" in p for p in pack.check_manifest(dict(pack.read_manifest(new), revision="2")))


def test_the_cli_refuses_an_older_pack_and_says_how(home, monkeypatch, capsys):
    from ai2 import cli
    monkeypatch.setattr(cli, "find_model_file", lambda f: "/m/" + f)
    make_collection("src", {"c.pdf": ["La capital es Madrid."]})
    old, new = str(home / "old.ai2pack"), str(home / "new.ai2pack")
    pack.export_pack("src", old, dict(TEMPLATE, id="everyday", version="2026-08-01", revision=1))
    pack.export_pack("src", new, dict(TEMPLATE, id="everyday", version="2026-09-16", revision=2))
    assert cli.main(["knowledge", "install", new]) == 0
    assert "Installed everyday" in capsys.readouterr().out
    assert cli.main(["knowledge", "install", old]) == 1
    assert "which is older; install it anyway with --force" in capsys.readouterr().err
    assert cli.main(["knowledge", "install", old, "--force"]) == 0
    assert "Put everyday back from version 2026-09-16 to the older" in capsys.readouterr().out
    # and a reinstall of the same file says so rather than claiming an update
    assert cli.main(["knowledge", "install", old]) == 0
    assert "Reinstalled everyday, replacing version 2026-08-01 with" in capsys.readouterr().out


def test_a_manifest_that_unpacks_huge_is_refused_before_it_is_read(home):
    """read_manifest used to read the whole member before any size check, so
    a small file could unpack to an enormous manifest. The declared size is
    checked first, and then the read is capped, because the declared size is
    the zip's word and not the truth."""
    import zipfile
    make_collection("c", {"c.pdf": ["La capital es Madrid."]})
    good = str(home / "good.ai2pack")
    pack.export_pack("c", good, TEMPLATE)
    with zipfile.ZipFile(good) as z:
        index = z.read("index.sqlite")
    bomb = str(home / "bomb.ai2pack")
    with zipfile.ZipFile(bomb, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.yml", "a: " + "b" * (pack.MANIFEST_MAX + 1000))
        z.writestr("index.sqlite", index)
    assert os.path.getsize(bomb) < 100_000            # tiny on disk, large unpacked
    with pytest.raises(pack.PackError, match="a manifest is a page of YAML"):
        pack.read_manifest(bomb)
    assert doc.list_collections() == ["c"]


def test_where_a_pack_came_from_is_recorded_on_this_machine(home):
    """Not in the pack (the artifact stays manifest.yml + index.sqlite) but
    beside it, so `ai-2 knowledge list` can still say where a pack came from
    when the machine is offline or the catalog has changed since."""
    make_collection("src", {"c.pdf": ["La capital es Madrid."]})
    out = str(home / "p.ai2pack")
    pack.export_pack("src", out, dict(TEMPLATE, id="everyday"))
    pack.install_pack(out)
    origin = pack.origin_of("everyday")
    assert origin["from"] == "file" and origin["file"] == "p.ai2pack"
    assert origin["sha256"] == pack.sha256_file(out) and origin["installed"]
    assert pack.origin_of("src") is None                 # a collection of one's own has none
    # what the catalog path records
    pack.install_pack(out, origin={"from": pack.CATALOG_ORIGIN, "id": "everyday",
                                   "url": "https://example.org/everyday.ai2pack", "sha256": "a" * 64})
    assert pack.origin_of("everyday")["from"] == "community catalog"
    # There is one catalog, the community's, with the project's own packs in it
    # (Rafael, 2026-09-19). A record written before 0.18.7 says "official
    # catalog" and reads as the same thing.
    assert pack.origin_label({"from": "official catalog"}) == "community catalog"
    assert pack.origin_label({"from": "file"}) == "file" and pack.origin_label(None) == "unknown source"
    assert pack.origin_of("everyday")["url"].startswith("https://")
    # the pack file itself is unchanged: an installed pack is still two members plus this local note
    import zipfile
    with zipfile.ZipFile(out) as z:
        assert sorted(z.namelist()) == ["index.sqlite", "manifest.yml"]


def test_a_download_stops_when_it_outgrows_the_catalog_and_never_leaves_https(home, monkeypatch):
    """Two cheap rules: stop reading once the response passes the size the
    catalog declares, and refuse a redirect that drops out of HTTPS."""
    import io
    entry = {"id": "big", "url": "https://example.org/big.ai2pack", "version": "1",
             "size_bytes": 1024, "sha256": "0" * 64}

    class FakeResp(io.BytesIO):
        status = 200
        headers = {"Content-Length": "1024"}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(pack.urllib.request, "build_opener",
                        lambda *a: type("O", (), {"open": lambda self, req, timeout=0: FakeResp(b"x" * 10_000)})())
    with pytest.raises(pack.PackError, match="larger than the catalog says"):
        pack.download_pack(entry, str(home / "dl"))
    assert not [f for f in os.listdir(home / "dl") if f.endswith(".part")]
    with pytest.raises(pack.PackError, match="not https"):
        pack.download_pack(dict(entry, url="http://example.org/big.ai2pack"), str(home / "dl"))
    # plain http to this machine crosses no network, so it is allowed (the
    # catalog test above serves a real pack that way)
    assert pack.is_safe_url("http://127.0.0.1:8000/p.ai2pack") and pack.is_safe_url("https://example.org/p")
    assert not pack.is_safe_url("http://example.org/p") and not pack.is_safe_url("ftp://example.org/p")
    handler = pack.HttpsOnlyRedirect()
    with pytest.raises(pack.PackError, match="not https"):
        handler.redirect_request(None, None, 302, "Found", {}, "http://elsewhere.example/p.ai2pack")


def test_an_updated_machine_is_told_the_packs_exist(home, monkeypatch, capsys):
    """An update changes packages, never a person's documents, so a machine
    brought up to date never gains the packs a fresh ISO install starts with.
    One line after a successful update is the only thing that says so."""
    from ai2 import cli
    entry = {"id": "ai2-help", "title": "AI-2 Help", "version": "2026-09-16", "languages": ["en"],
             "license": "MIT", "embedder": V2, "url": "https://example.org/a.ai2pack",
             "size_bytes": 1, "sha256": "0" * 64, "documents": 1, "parts": 1}
    monkeypatch.setattr(pack, "load_catalog", lambda: [entry])

    from ai2 import software
    monkeypatch.setattr(software, "update", lambda: 0)
    args = type("A", (), {"gui": False})()
    assert cli.cmd_update(args) == 0
    out = capsys.readouterr().out
    assert "no knowledge packs" in out and "ai-2 knowledge browse" in out and "Applications > AI-2 > Knowledge Packs" in out and "ai2-help" in out

    # a machine that already has one is not nagged, and a failed update says nothing about packs
    make_collection("mine", {"a.txt": ["Hello."]})
    out_path = str(home / "p.ai2pack")
    pack.export_pack("mine", out_path, dict(TEMPLATE, id="ai2-help"))
    pack.install_pack(out_path)
    capsys.readouterr()
    assert cli.cmd_update(args) == 0
    assert "no knowledge packs" not in capsys.readouterr().out
    monkeypatch.setattr(software, "update", lambda: 1)
    assert cli.cmd_update(args) == 1
    assert "no knowledge packs" not in capsys.readouterr().out


def test_every_pack_in_the_packaged_catalog_names_its_maker_and_the_listing_points_home(home, capsys):
    """The package carries a copy of the community catalog, where every entry
    says who made the pack, the project's own included. The listing shows it
    and ends on the catalog's address, which is where packs are downloaded and
    shared (Rafael, 2026-09-19: "point there from EVERYWHERE")."""
    from ai2 import cli
    entries = pack.load_catalog()
    assert entries and all(e.get("contact") for e in entries)
    assert cli.main(["knowledge", "available"]) == 0
    out = capsys.readouterr().out
    assert "by ProWoos-Devs" in out and "community catalog" in out
    assert pack.CATALOG_URL in out and "share" in out
    assert "official catalog" not in out and "official pack" not in out   # (everyday lists official languages)
    assert "196 countries" in out, "the sentence about what is in a pack"
