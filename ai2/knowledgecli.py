"""`ai-2 doc` and `ai-2 knowledge`: the documents on this computer and the
Knowledge Packs, including the Search Knowledge window.

Split out of cli.py, which had grown to 2500 lines and 30 commands, so that a
change to Search Knowledge is not read in the same file as `serve` and
`update-check`. Nothing here behaves differently from before the move.

Helpers that belong to the rest of the tool are reached through the cli module
(`detect()`, not `detect()`), which also keeps a test that replaces
`cli.something` working on this code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap

from . import branding, runner, serverstate
from .detect import detect
from .i18n import tr
from .models import is_starter, load_catalog
from .runtime import find_model_file, installed_models
from .state import load_score


def cmd_doc(args) -> int:
    """`ai-2 doc index|ask|search|list|forget`: questions about your own documents."""
    from . import doc as docmod
    action = getattr(args, "doc_cmd", None)
    collection = getattr(args, "collection", None)
    if collection is not None and not docmod.valid_collection(collection):
        print(f"error: {collection!r} is not a collection name (lower-case letters, digits, '.', '-', '_')",
              file=sys.stderr)
        return 1
    if action == "index":
        return _doc_index(args, docmod)
    if action == "ask":
        return _doc_ask(args, docmod)
    if action == "search":
        return _doc_search(args, docmod)
    if action == "forget":
        return _doc_forget(args, docmod)
    names = docmod.list_collections()
    shown = [(n, docmod.open_store(docmod.index_path(n))) for n in names]
    shown = [(n, c) for n, c in shown if docmod.list_documents(c)]
    if not shown:
        print("No documents indexed yet. Add one with:  ai-2 doc index FILE   (text, PDF, DOCX or a scan)")
        return 0
    from . import pack as packmod
    print("Documents the AI can answer about:")
    for name, conn in shown:
        manifest = packmod.manifest_of(name)
        what = (f"pack {manifest.get('title')}, version {manifest.get('version')}, license {manifest.get('license')}"
                if manifest else docmod.index_path(name))
        print(f"\n  {name}  (embedder {docmod.store_model(conn)}, {what})")
        for d in docmod.list_documents(conn):
            print(f"    {d['name']:<40} {d['words']:>7} words  {d['chunks']:>5} parts  added {d['added']}")
    print('\nAsk:  ai-2 doc ask "your question"    Passages only:  ai-2 doc search "..."    Remove:  ai-2 doc forget NAME')
    return 0


def _doc_forget(args, docmod) -> int:
    """One document by name (wherever it is, unless that is ambiguous), or
    --all of a collection, which removes the collection itself."""
    names = docmod.list_collections()
    if args.all:
        target = args.collection or docmod.DEFAULT_COLLECTION
        if target not in names:
            if args.collection:
                print(f"No collection named {target!r} (ai-2 doc list shows them).")
                return 1
            print("The index was already empty.")
            return 0
        n = len(docmod.list_documents(docmod.open_store(docmod.index_path(target))))
        docmod.remove_collection(target)
        if n:
            print(f"Forgot {n} document{'s' if n != 1 else ''} and the collection {target}.")
        else:
            print("The index was already empty." if target == docmod.DEFAULT_COLLECTION
                  else f"Removed the empty collection {target}.")
        return 0
    if not args.name:
        print("error: name a document (ai-2 doc list) or pass --all", file=sys.stderr)
        return 1
    where = [n for n in ([args.collection] if args.collection else names)
             if n in names and args.name in {d["name"] for d in docmod.list_documents(docmod.open_store(docmod.index_path(n)))}]
    if not where:
        print(f"No document named {args.name!r} (ai-2 doc list shows the names).")
        return 1
    if len(where) > 1:
        print(f"error: {args.name!r} is in more than one collection ({', '.join(where)}); say which with --in NAME",
              file=sys.stderr)
        return 1
    docmod.forget(docmod.open_store(docmod.index_path(where[0])), name=args.name)
    print(f"Forgot 1 document." + ("" if where[0] == docmod.DEFAULT_COLLECTION else f" (collection {where[0]})"))
    return 0


def cmd_knowledge(args) -> int:
    """`ai-2 knowledge export|install|list|remove`: knowledge packs, a
    collection of documents in one file that other computers can install."""
    import yaml
    from . import doc as docmod
    from . import pack as packmod
    action = getattr(args, "knowledge_cmd", None)
    try:
        if action == "export":
            if not docmod.valid_collection(args.name) or args.name not in docmod.list_collections():
                print(f"error: no collection named {args.name!r} (ai-2 doc list shows them)", file=sys.stderr)
                return 1
            template = None
            if args.manifest:
                with open(args.manifest, encoding="utf-8") as fh:
                    template = yaml.safe_load(fh) or {}
                if not isinstance(template, dict):
                    print(f"error: {args.manifest} is not a YAML mapping", file=sys.stderr)
                    return 1
            out = args.output or f"{(template or {}).get('id', args.name)}{packmod.SUFFIX}"
            m = packmod.export_pack(args.name, out, template)
            print(f"Wrote {out} ({os.path.getsize(out) // 1024} KB): {m['title']}, version {m['version']}, "
                  f"{m['index']['documents']} document(s), {m['index']['parts']} parts, embedder {m['embedder']['id']}, "
                  f"license {m['license']}.")
            print("Document paths on this computer are not included. On the other computer:  "
                  f"ai-2 knowledge install {os.path.basename(out)}")
            return 0
        if action == "available":
            entries = packmod.load_catalog()
            if args.term:
                term = args.term.lower()
                entries = [e for e in entries if term in f"{e.get('id')} {e.get('title')}".lower()]
            if not entries:
                print("No knowledge packs to fetch by name yet. A pack file works the same way:  "
                      "ai-2 knowledge install FILE.ai2pack")
                print(f"The community catalog, to get packs and to share one you made:  {packmod.CATALOG_URL}")
                return 0
            installed = {m.get("id"): m for _, m in packmod.installed_packs()}
            print("Knowledge packs (ai-2 knowledge install ID):")
            for e in entries:
                here = installed.get(e["id"])
                if here is None:
                    state = ""
                elif packmod.revision_of(e) > packmod.revision_of(here):
                    state = f"  [installed {here.get('version')}, newer available]"
                else:
                    state = "  [installed]"
                by = f", by {e['contact']}" if e.get("contact") else ""
                print(f"  {e['id']:<22} {e.get('title')}  ({e.get('parts')} parts, "
                      f"{int(e.get('size_bytes', 0)) // 1024} KB, {', '.join(e.get('languages') or [])}, "
                      f"{e.get('license')}{by}){state}")
                if e.get("description"):
                    print(f"  {'':<22} {e['description']}")
            # One catalog, the community's, with the project's own packs in it.
            # What is fetched by name is the copy of it inside the signed
            # package; a pack added to the catalog since is installed from its
            # file until the next ai-2 release lists it.
            print("\nThis is the AI-2 community catalog as this ai-2 release carries it, inside the "
                  "signed package.\nThe catalog itself, with any pack added since, every download, and "
                  f"how to share one you made:\n{packmod.CATALOG_URL}\n"
                  "A downloaded pack installs with:  ai-2 knowledge install FILE.ai2pack\n"
                  "To pick from this list by number:  ai-2 knowledge browse   "
                  "(Applications > AI-2 > Knowledge Packs)")
            return 0
        if action == "browse":
            if args.window:
                # the menu entry: a window big enough for the list, like the setup's
                from . import about
                if about.open_window(about.terminal_window("Knowledge Packs", "100x38",
                                                           ["ai-2", "knowledge", "browse"])):
                    return 0
                print("No terminal program found to open the window; showing it here.", file=sys.stderr)
            return _knowledge_browse(packmod, docmod)
        if action == "update":
            return _knowledge_update(args.ids, packmod, docmod)
        if action == "install":
            sources = list(args.file)
            if len(sources) > 1:
                # `ai-2 knowledge install ai2-help everyday`: one after the other,
                # and one that fails does not stop the rest.
                if args.as_name:
                    print("error: --as names one collection, so it goes with one pack", file=sys.stderr)
                    return 1
                worst = 0
                for n, one in enumerate(sources):
                    if n:
                        print()
                    try:
                        worst = max(worst, cmd_knowledge(argparse.Namespace(
                            knowledge_cmd="install", file=[one], as_name=None, force=args.force)))
                    except (packmod.PackError, OSError) as exc:
                        print(f"error: {one}: {exc}", file=sys.stderr)
                        worst = 1
                return worst
            source = sources[0]
            origin = None
            entry = packmod.catalog_entry(source)
            if entry is None and not os.path.exists(source):
                print(f"error: no pack file at {source!r} and nothing by that name in the catalog "
                      "(ai-2 knowledge available)", file=sys.stderr)
                return 1
            if entry is not None:
                source = _fetch_cataloged_pack(entry, packmod, docmod)
                origin = {"from": packmod.CATALOG_ORIGIN, "id": entry["id"], "url": entry["url"],
                          "sha256": entry["sha256"], "version": entry.get("version")}
            collection, m, previous = packmod.install_pack(source, name=args.as_name, force=args.force,
                                                          origin=origin)
            model = runner._catalog_entry(m["embedder"]["id"])
            here, incoming = packmod.revision_of(previous or {}), packmod.revision_of(m)
            if previous is None:
                verb = f"Installed {collection},"
            elif incoming > here:
                verb = f"Updated {collection} from version {previous.get('version')} to"
            elif incoming == here:
                verb = f"Reinstalled {collection}, replacing version {previous.get('version')} with"
            else:
                verb = f"Put {collection} back from version {previous.get('version')} to the older"
            print(f"{verb} {m['title']} version {m['version']}: {m['index']['documents']} document(s), "
                  f"{m['index']['parts']} parts. License {m['license']}.")
            if m.get("attribution"):
                print(m["attribution"])
            if model and find_model_file(model["file"]) is None:
                print(f"The pack is searched with {model['label']} ({model['file_mb']} MB); downloading it now.")
                if runner._pull_model(model) != 0:
                    print("The pack is installed; the download can be repeated with:  "
                          f"ai-2 model pull {model['id']}", file=sys.stderr)
                    return 1
            print(f'Search it:  ai-2 doc search --in {collection} "your question"')
            return 0
        if action == "remove":
            name = args.name
            if packmod.manifest_of(name) is None:
                # `ai-2 knowledge install PACK --as OTHER` puts a pack in a
                # collection of another name, and every list and window shows
                # the catalog id, so the id has to work here too.
                by_id = [n for n, m in packmod.installed_packs() if m.get("id") == name]
                if len(by_id) > 1:
                    print(f"error: {name!r} is installed more than once, as {', '.join(sorted(by_id))}; "
                          "name the one to remove", file=sys.stderr)
                    return 1
                if not by_id:
                    print(f"error: {name!r} is not an installed knowledge pack (ai-2 knowledge list); "
                          "a collection of your own goes with:  ai-2 doc forget --all --in NAME", file=sys.stderr)
                    return 1
                name = by_id[0]
            docmod.remove_collection(name)
            print(f"Removed the pack {name}." if name == args.name
                  else f"Removed the pack {args.name}, which was installed as {name}.")
            return 0
        packs = packmod.installed_packs()
        if not packs:
            print("No knowledge packs installed. Install one with:  ai-2 knowledge install FILE.ai2pack")
            return 0
        print("Knowledge packs:")
        for name, m in packs:
            idx = m.get("index") or {}
            origin = packmod.origin_of(name) or {}
            where = packmod.origin_label(origin)
            print(f"  {name:<24} {m.get('title')}, version {m.get('version')}, {idx.get('parts')} parts, "
                  f"license {m.get('license')}")
            print(f"  {'':<24} from the {where}" if where != "file"
                  else f"  {'':<24} installed from the file {origin.get('file')}")
        return 0
    except (packmod.PackError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _doc_embedder(docmod, hw, wanted: str | None, model_id: str | None, collection: str):
    """The embedding model a `doc index` run will use, or None after printing
    why there is none. Without `--embedder` this is what AI-2 picks from the
    machine's RAM, which on a roomy machine is the multilingual model. That is
    the right default for a person's own documents and the wrong one for a
    pack meant to be shared: vectors only compare with vectors from the same
    model, so an English pack built with the 345 MB multilingual model makes
    everyone who installs it fetch 345 MB, when the 85 MB English one is
    already on every machine installed from an ISO."""
    from .models import RAM_HEADROOM_MIB, embedding_models
    if model_id and wanted and wanted != model_id:
        print(f"error: the collection {collection!r} was built with {model_id}, and a collection cannot change "
              "its embedding model, because vectors made by two models cannot be compared. Index into a new "
              f"collection instead:  ai-2 doc index --in NEWNAME --embedder {wanted} FILE...", file=sys.stderr)
        return None
    if model_id:
        return runner._catalog_entry(model_id)
    if wanted:
        model = next((m for m in embedding_models() if m["id"] == wanted), None)
        if model is None:
            ids = ", ".join(m["id"] for m in embedding_models())
            print(f"error: no embedding model called {wanted!r} (this AI-2 knows: {ids})", file=sys.stderr)
            return None
        budget = max(0, hw.ram_mib - RAM_HEADROOM_MIB)
        if model["ram_peak_mb"] > budget:
            print(f"error: {model['label']} needs about {model['ram_peak_mb']} MB while indexing and this "
                  f"computer can spare {budget} MB. Index on a machine with more memory, or leave --embedder "
                  "out to let AI-2 pick one that fits.", file=sys.stderr)
            return None
        return model
    model = docmod.choose_embedder(hw.ram_mib)
    if model is None:
        print("error: no embedding model fits this computer's RAM (the smallest needs about 300 MB free).",
              file=sys.stderr)
    return model


def _doc_index(args, docmod) -> int:
    import subprocess
    import time
    import zipfile
    hw = detect()
    collection = args.collection or docmod.DEFAULT_COLLECTION
    conn = docmod.open_store(None if collection == docmod.DEFAULT_COLLECTION else docmod.index_path(collection))
    model_id = docmod.store_model(conn)
    model = _doc_embedder(docmod, hw, getattr(args, "embedder", None), model_id, collection)
    if model is None:
        return 1
    if find_model_file(model["file"]) is None:
        print(f"The documents index uses {model['label']} ({model['file_mb']} MB); downloading it first.")
        if runner._pull_model(model) != 0:
            return 1
    url = runner._ensure_server(hw, model, docmod.EMBED_PORT, serverstate.EMBED, wait=args.wait)
    if url is None:
        return 1
    client = docmod.EmbedClient(url, model)
    if model_id is None:
        docmod.set_store_model(conn, model["id"], int(model["dims"]))
    rc = 0
    prefix = model.get("prefix_document", "")
    for path in args.files:
        name = os.path.basename(path)
        try:
            pages, paged = docmod.extract_pages(path, lang=args.lang)
        except (RuntimeError, subprocess.CalledProcessError, OSError, zipfile.BadZipFile, KeyError) as exc:
            print(f"  skipped {name}: {exc}", file=sys.stderr)
            rc = 1
            continue
        if not any(p.split() for p in pages):
            print(f"  skipped {name}: no text found (a scanned PDF needs OCR: ai-2 workflow info documents)",
                  file=sys.stderr)
            rc = 1
            continue
        chunks, spans, words = docmod.make_chunks(pages, paged, lambda c: client.ntokens(prefix + c),
                                                  client.token_limit())
        print(f"{name}: {words} words in {len(chunks)} parts, indexing with {model['label']} "
              "(slow on an old CPU; you can leave it running) ...", flush=True)
        t0 = time.monotonic()

        def progress(done, total):
            elapsed = time.monotonic() - t0
            left = elapsed / done * (total - done) if done else 0
            print(f"\r  {done}/{total} parts, {int(elapsed)} s, about {int(left / 60) + 1} min left   ",
                  end="", flush=True)

        try:
            vectors = client.embed_documents(chunks, progress=progress)
        except OSError as exc:
            print(f"\n  error: the embedding server went away ({exc}); run the command again", file=sys.stderr)
            return 1
        docmod.add_document(conn, name, os.path.abspath(path), chunks, vectors, words, pages=spans)
        print(f"\r  {name}: {len(chunks)} parts indexed in {time.monotonic() - t0:.0f} s" + " " * 12)
    print('Ask about them:  ai-2 doc ask "your question"'
          + ("" if collection == docmod.DEFAULT_COLLECTION else f"   (or only these: --in {collection})"))
    return rc


def _server_busy(url: str, timeout: float = 2.0) -> bool:
    """True when llama-server is working on a request. It answers /slots from
    the loop that runs the model, so a poll that times out means busy (the
    same rule as the serve wrapper); a refused connection means nothing is
    there to be busy."""
    import json
    import socket
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/slots", timeout=timeout) as r:
            slots = json.loads(r.read(200000).decode("utf-8", "replace"))
    except (TimeoutError, socket.timeout):
        return True
    except urllib.error.URLError as exc:
        return isinstance(exc.reason, (TimeoutError, socket.timeout))
    except (OSError, ValueError):
        return False
    return any(isinstance(s, dict) and s.get("is_processing") for s in slots or [])


def _ensure_embed(hw, model: dict, wait: int):
    """The embedding server for this model. Scores only compare inside one
    model, so a search that covers two groups swaps the server between them
    (one port). A server busy with another model, an `ai-2 doc index` in
    progress, is left alone: stopping it would kill the indexing."""
    from . import doc as docmod
    running = serverstate.read_server(serverstate.EMBED)
    if running and running.get("model") and running["model"] != model["id"]:
        if _server_busy(f"http://127.0.0.1:{docmod.EMBED_PORT}/"):
            return None
        serverstate.stop_server(name=serverstate.EMBED)
    return runner._ensure_server(hw, model, docmod.EMBED_PORT, serverstate.EMBED, wait=wait)


def _interleave(groups: list[list[dict]]) -> list[dict]:
    """One from each group in turn. Scores from two embedding models do not
    compare, so neither group may crowd the other out of the top results."""
    merged = []
    for i in range(max((len(g) for g in groups), default=0)):
        merged.extend(g[i] for g in groups if i < len(g))
    return merged


def _distinct_docs(hits: list[dict], top: int) -> list[dict]:
    seen, kept = set(), []
    for h in hits:
        key = (h["collection"], h["doc"])
        if key not in seen:
            seen.add(key)
            kept.append(h)
        if len(kept) >= top:
            break
    return kept


def _doc_hits(args, docmod, hw, question: str, distinct: bool = False) -> list[dict] | None:
    """The parts of the indexed documents closest to the question, found by
    the embedding server (started on demand), across every collection unless
    --in names one. Collections built with different embedding models cannot
    share a question vector, so each group is searched in turn (Knowledge
    Packs first, then the person's own documents). Scores are not compared
    across groups. None, with the reason printed, when there is nothing to
    search or no server for any group."""
    from . import pack as packmod
    names = docmod.list_collections()
    if args.collection:
        if args.collection not in names:
            print(f"No collection named {args.collection!r} (ai-2 doc list shows them).", file=sys.stderr)
            return None
        names = [args.collection]
    stores = {n: docmod.open_store(docmod.index_path(n)) for n in names}
    info = {n: (docmod.store_model(c), docmod.list_documents(c)) for n, c in stores.items()}
    usable = [n for n, (model_id, docs) in info.items() if model_id and docs]
    if not usable:
        print("No documents indexed yet. Add one with:  ai-2 doc index FILE", file=sys.stderr)
        return None
    if args.doc:
        usable = [n for n in usable if args.doc in {d["name"] for d in info[n][1]}]
        if not usable:
            print(f"No document named {args.doc!r} (ai-2 doc list shows the names).", file=sys.stderr)
            return None
    groups: dict[str, list[str]] = {}
    for n in usable:
        groups.setdefault(info[n][0], []).append(n)
    pack_models, own_models, seen = [], [], []
    for n in usable:
        model_id = info[n][0]
        if model_id in seen:
            continue
        seen.append(model_id)
        if any(packmod.manifest_of(c) for c in groups[model_id]):
            pack_models.append(model_id)
        else:
            own_models.append(model_id)
    # `distinct` is for a person reading results: one per document, because two
    # parts of the same FAQ took two of Rafael's three slots (2026-09-18) and the
    # rest of any document is one keypress away. `doc ask` keeps every part: the
    # chat model may need two parts of one document to answer.
    fetch = args.top * 4 if distinct else args.top
    per_group: list[list[dict]] = []
    searched: list[str] = []
    last_error = None
    for model_id in pack_models + own_models:
        emb = runner._catalog_entry(model_id)
        if emb is None:
            last_error = (f"error: {', '.join(groups[model_id])} was built with {model_id}, "
                          "which is no longer in the catalog; "
                          "rebuild it:  ai-2 doc forget --all --in NAME")
            print(last_error, file=sys.stderr)
            continue
        url = _ensure_embed(hw, emb, wait=args.wait)
        if url is None:
            last_error = "no embedding server"
            print(f"Not searched this time: {', '.join(groups[model_id])} (the embedding server is busy "
                  "or did not start; if a document is being indexed, ask again when it finishes)",
                  file=sys.stderr)
            continue
        qvec = docmod.EmbedClient(url, emb).embed_query(question)
        hits = docmod.search_collections({n: stores[n] for n in groups[model_id]},
                                         qvec, top=fetch, doc=args.doc)
        if distinct:
            hits = _distinct_docs(hits, args.top)
        per_group.append(hits)
        searched.extend(groups[model_id])
    hits = _interleave(per_group)[:args.top]
    if not hits:
        if not searched:
            if last_error is None:
                print("No documents indexed yet. Add one with:  ai-2 doc index FILE", file=sys.stderr)
            return None
        print("Nothing in the indexed documents matches the question.")
        return None
    several = len({h["collection"] for h in hits}) > 1
    manifests = {n: packmod.manifest_of(n) for n in {h["collection"] for h in hits}}
    for h in hits:
        h["cite"] = docmod.cite(h, with_collection=several)
        h["url"] = packmod.source_url(manifests.get(h["collection"]), h["doc"])
        h["manifest"] = manifests.get(h["collection"])
    return hits


def _pack_terms(hits: list[dict]) -> list[str]:
    """One line per pack the hits came from: its license and attribution, which
    CC BY-SA and the BOE reuse terms ask to show wherever the text is reused,
    and, for a pack that came from a file rather than the catalog, that it
    did. An answer is read here, so this is where it has to be said."""
    from . import pack as packmod
    out = []
    seen = set()
    for h in hits:
        m = h.get("manifest")
        if m and m.get("id") not in seen:
            seen.add(m.get("id"))
            attribution = str(m.get("attribution") or "").strip()
            line = f"From the pack {m.get('title')} ({m.get('license')})" + (f". {attribution}" if attribution else "")
            if packmod.origin_label(packmod.origin_of(h["collection"])) == "file":
                line += "  [installed from a file, not from the catalog]"
            out.append(line)
    return out


def _doc_show_hits(hits, width) -> None:
    import textwrap
    from .doc import wrap_paragraphs as docmod_wrap
    for i, h in enumerate(hits, 1):
        print(f"\n[{i}] {h['cite']}" + (f"  {h['url']}" if h.get("url") else ""))
        print(docmod_wrap(h["text"], width, "    "))
    terms = _pack_terms(hits)
    if terms:
        print()
        for line in terms:
            print(textwrap.fill(line, width=width + 4))


def _doc_reader_page(hit: dict, docmod) -> str | None:
    """The whole document a result came from, as a small HTML page for a text
    browser: its paragraphs, an anchor where the result begins, the source as a
    link that can be followed, and the pack's licence and attribution."""
    import html
    conn = docmod.open_store(docmod.index_path(hit["collection"]))
    rows = conn.execute("SELECT chunks.text FROM chunks JOIN docs ON docs.id = chunks.doc_id "
                        "WHERE docs.name = ? ORDER BY chunks.ord", (hit["doc"],)).fetchall()
    conn.close()
    if not rows:
        return None
    paras = docmod.join_paragraphs([r[0] for r in rows])
    # where the result begins: the paragraph holding its first words
    opening = " ".join(docmod.flat(hit["text"]).split()[:8])
    at = next((i for i, para in enumerate(paras) if opening and opening in para), None)
    body = []
    for i, para in enumerate(paras):
        mark = '<a name="hit"></a>' if i == at else ""
        body.append(f"{mark}<p>{html.escape(para)}</p>")
    foot = []
    if hit.get("url"):
        u = html.escape(hit["url"], quote=True)
        foot.append(f'<p>Source: <a href="{u}">{u}</a></p>')
    foot += [f"<p>{html.escape(line)}</p>" for line in _pack_terms([hit])]
    title = html.escape(hit["doc"])
    return (f"<html><head><meta charset=\"utf-8\"><title>{title}</title></head><body>"
            f"<h1>{title}</h1>{''.join(body)}<hr>{''.join(foot)}"
            "<p><i>q closes this and returns to your questions. / searches inside the document.</i></p>"
            "</body></html>")


def _doc_open_reader(hit: dict, docmod, which=None, run=None) -> bool:
    """Open the document in w3m when it is there, positioned at the result.
    A terminal prints text once, at one width, and cannot re-lay it out; w3m
    owns its window, so the text follows the window when it is resized
    (measured: a 60-column window resized to 120, lines went from 62 to 122),
    scrolls, and searches inside the document. It is on the AI-2 image; a
    machine brought up to date gets it with `ai-2 install text-browser`, and
    without it the text is printed in place as before. False when not used."""
    import shutil
    import subprocess
    import tempfile
    which = which or shutil.which
    run = run or subprocess.run
    if not (sys.stdin.isatty() and sys.stdout.isatty()) or not which("w3m"):
        return False
    page = _doc_reader_page(hit, docmod)
    if page is None:
        return False
    with tempfile.TemporaryDirectory(prefix="ai2-read-") as tmp:
        path = os.path.join(tmp, "document.html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(page)
        try:
            # confirm_qq off: q should close the document, not ask whether it may
            run(["w3m", "-o", "confirm_qq=false", "-T", "text/html", f"file://{path}#hit"])
        except OSError:
            return False
    return True


def _doc_read_more(hit: dict, radius: int, docmod, width: int) -> bool:
    """More of the document one result came from: the whole of a short one, a
    widening window onto a long one. True while there is still more to show.
    A passage of 110 words answers a question; deciding whether to trust it, or
    getting the step after the one it names, takes the text around it. The
    Gopher menus had this from the start (every hit links to its document); the
    window a person actually sits at did not (Rafael, 2026-09-18, reading three
    results of which only the second was the one he wanted)."""
    import textwrap
    conn = docmod.open_store(docmod.index_path(hit["collection"]))
    texts, first, last, total = docmod.parts_around(conn, hit["doc"], hit["ord"], radius)
    conn.close()
    if not texts:
        print("That document is no longer in the index.")
        return False
    whole = first == 0 and last == total - 1
    where = hit["doc"] if whole else f"{hit['doc']}, parts {first + 1} to {last + 1} of {total}"
    print(f"\n{where}" + (f"  {hit['url']}" if hit.get("url") else ""))
    print("-" * min(width, len(where)))
    print(textwrap.indent(docmod.join_parts(texts, width=width - 4), "    "))
    terms = _pack_terms([hit])
    if terms:
        print()
        for line in terms:
            print(textwrap.fill(line, width=width + 4))
    return not whole


def _fetch_cataloged_pack(entry: dict, packmod, docmod) -> str:
    """Download a cataloged pack and return the file, showing progress. The
    size and SHA-256 are checked inside download_pack, which keeps nothing that
    does not match."""
    print(f"{entry['title']} ({int(entry.get('size_bytes', 0)) // 1024} KB), "
          f"{entry.get('license')}. Downloading ...")

    def progress(done, total):
        print(f"\r  {done // 1024} KB of {total // 1024} KB   " if total else
              f"\r  {done // 1024} KB   ", end="", flush=True)

    path = packmod.download_pack(entry, os.path.join(docmod.data_dir(), "packs"), progress=progress)
    print()
    return path


def _install_cataloged_pack(entry: dict, packmod, docmod) -> int:
    """Fetch, install and report one pack from the catalog, and pull the model
    it is searched with if this machine does not have it yet. 0 when the pack
    is installed and searchable."""
    path = _fetch_cataloged_pack(entry, packmod, docmod)
    origin = {"from": packmod.CATALOG_ORIGIN, "id": entry["id"], "url": entry["url"],
              "sha256": entry["sha256"], "version": entry.get("version")}
    collection, m, previous = packmod.install_pack(path, origin=origin)
    if previous is not None and packmod.revision_of(m) > packmod.revision_of(previous):
        what = f"Updated {collection} from version {previous.get('version')} to {m['version']}:"
    else:
        what = f"Installed {collection}: {m['title']} version {m['version']},"
    print(f"{what} {m['index']['documents']} document(s), {m['index']['parts']} parts. License {m['license']}.")
    if m.get("attribution"):
        print(m["attribution"])
    model = runner._catalog_entry(m["embedder"]["id"])
    if model and find_model_file(model["file"]) is None:
        print(f"The pack is searched with {model['label']} ({model['file_mb']} MB); downloading it now.")
        if runner._pull_model(model) != 0:
            print("The pack is installed; the download can be repeated with:  "
                  f"ai-2 model pull {model['id']}", file=sys.stderr)
            return 1
    return 0


def _knowledge_model_cost(entry: dict) -> str | None:
    """The sentence about the embedding model a pack is searched with, when
    this computer still has to download it. It is the real cost of a first
    pack (85 MB against a few hundred KB), so it is said before the download."""
    model = runner._catalog_entry(str(entry.get("embedder") or ""))
    if model is None or find_model_file(model["file"]) is not None:
        return None
    return (f"Packs built with {model['label']} are searched with it, and this computer does not have it yet: "
            f"a {model['file_mb']} MB download, once.")


def _knowledge_browse(packmod, docmod) -> int:
    """Applications > AI-2 > Knowledge Packs, and `ai-2 knowledge browse`."""
    import shutil
    from . import packbrowse
    width = max(60, min(100, shutil.get_terminal_size((100, 30)).columns) - 4)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    return packbrowse.browse(install=lambda entry: _install_cataloged_pack(entry, packmod, docmod),
                             model_cost=_knowledge_model_cost, interactive=interactive, width=width,
                             banner=branding.compact() if interactive else "")


def _knowledge_update(ids: list[str], packmod, docmod) -> int:
    """`ai-2 knowledge update [ID ...]`: bring installed packs up to the newest
    revision the catalog knows. With no ids, every pack that has one."""
    from . import packbrowse
    newer = packbrowse.outdated()
    if ids:
        known = {e["id"] for e in newer}
        for pid in ids:
            if pid not in known:
                print(f"{pid}: nothing newer in the catalog this AI-2 carries.")
        newer = [e for e in newer if e["id"] in ids]
    _say_what_a_file_is_holding_back(packmod, ids)
    if not newer:
        if not ids:
            print("Every installed Knowledge Pack is the newest version this AI-2 knows of.\n"
                  "The list of packs comes with AI-2 itself, so  ai-2 update  is what brings newer ones into view.")
        return 0
    worst = 0
    for n, entry in enumerate(newer):
        if n:
            print()
        try:
            worst = max(worst, _install_cataloged_pack(entry, packmod, docmod))
        except (packmod.PackError, OSError) as exc:
            print(f"error: {entry['id']}: {exc}", file=sys.stderr)
            worst = 1
    return worst


def _say_what_a_file_is_holding_back(packmod, ids: list[str]) -> None:
    """A pack installed from a file with a revision at or above the catalog's
    is left alone by `update`, and silence there is how a file could keep the
    catalog copy out for good. Say which one, and how to take it back."""
    for collection, m in packmod.installed_packs():
        pid = m.get("id")
        if ids and pid not in ids:
            continue
        if packmod.origin_label(packmod.origin_of(collection)) != "file":
            continue
        entry = packmod.catalog_entry(pid)
        if entry is None:
            continue
        here, there = packmod.revision_of(m), packmod.revision_of(entry)
        if here >= there:
            print(f"{pid} was installed from a file (revision {here}); the catalog has revision {there}, "
                  f"so update leaves it alone.\nTake the catalog copy with:  "
                  f"ai-2 knowledge install {pid} --force")


def _doc_more_hints() -> None:
    """Where more knowledge comes from. Printed in both states of the Search
    Knowledge window, with packs and without, because they are the same two
    things a person can do next (Rafael, 2026-09-18)."""
    from . import pack as packmod
    print(tr("\nAdd or update Knowledge Packs:  Applications > AI-2 > Knowledge Packs   (ai-2 knowledge browse)"))
    print(tr("Your own documents:            ai-2 doc index FILE"))
    print(tr("Get packs, share yours:        {url}").format(url=packmod.CATALOG_URL))


def _offer_the_packs(docmod, width) -> bool:
    """The Search Knowledge window has nothing to search. Naming a command in a
    window that closes on the next keypress is not an offer, so this asks, and
    installs. True when something was installed and the search can go on.

    Only when a person is there to answer: a script or a pipe gets the command
    to run instead."""
    import textwrap
    from . import pack as packmod
    if not sys.stdin.isatty():
        return False
    try:
        entries = packmod.load_catalog()
    except Exception:                               # a broken catalog must not shadow the message
        return False
    if not entries:
        return False
    model = runner._catalog_entry((entries[0].get("embedder") or ""))
    packs_kb = sum(int(e.get("size_bytes") or 0) for e in entries) // 1024
    need_model = model is not None and find_model_file(model["file"]) is None
    print(tr("\nThese are ready to install, and then searchable with no network at all:\n"))
    for e in entries:
        print(f"  {e['id']:<18} {e.get('title')}  ({e.get('parts')} parts, "
              f"{int(e.get('size_bytes', 0)) // 1024} KB, {e.get('license')})")
    total = f"{packs_kb} KB"
    if need_model:
        total += f" plus the {model['file_mb']} MB {model['label']}, once, which every pack here is searched with"
    print(textwrap.fill(f"\nThat is {total}.", width=width + 4))
    try:
        answer = input(tr("\nInstall them now? [Y/n]: ")).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    if answer and not answer.startswith(("y", "s", "j")):
        print(tr("\nNothing installed. When you want them:  ai-2 knowledge install ai2-help"))
        return False
    done = 0
    for e in entries:
        print()
        try:
            if _install_cataloged_pack(e, packmod, docmod) == 0:
                done += 1
        except (packmod.PackError, OSError) as exc:
            print(f"error: {e['id']}: {exc}", file=sys.stderr)
    return done > 0


def _doc_search(args, docmod) -> int:
    """The closest parts themselves, with where they come from, and no chat
    model: seconds instead of minutes on the old machines, and the text is
    the document's own, so nothing can be made up.

    With no question it asks for one and keeps asking, which is what the
    Search Knowledge menu entry runs. A question on a terminal is the first
    round of that same loop (the setup's first question, and typing
    `ai-2 doc search "..."` in a window), so a number still opens the
    document. A pipe or a script stays one-shot."""
    import shutil
    question = " ".join(args.question).strip()
    width = max(40, min(100, shutil.get_terminal_size((80, 24)).columns) - 4)
    if question and not sys.stdin.isatty():
        hits = _doc_hits(args, docmod, detect(), question, distinct=not args.doc)
        if hits is None:
            return 1
        _doc_show_hits(hits, width)
        return 0
    rc = _doc_search_loop(args, docmod, width, first=question or None)
    # The Search Knowledge menu entry runs this in a terminal that closes the
    # moment the command returns. Every round of the loop waits for input, so
    # the window stays by itself; a round that never happens does not, and the
    # message explaining why (nothing indexed, no model, no server) flashes past
    # unread. Found on the 2016 reference laptop, where an upgraded AI-2 has no
    # packs: the window opened and vanished (2026-09-17).
    if rc and sys.stdin.isatty():
        from . import about
        print()
        about.wait_for_enter()
    return rc


def _doc_search_loop(args, docmod, width, first: str | None = None) -> int:
    """Ask, search, print, ask again. The first screen says what this is,
    because the difference from AI-2 Chat is the point: these are passages
    from the documents on this computer, not something a model wrote.
    `first` is a question already typed (the setup window, or argv); it is
    searched after the first screen, then the loop continues."""
    import textwrap
    hw = detect()
    print(branding.compact())
    print(textwrap.fill(tr("This searches the documents and knowledge packs on this computer and shows "
                           "the passages that match, each with the document it came from. It is not AI-2 "
                           "Chat: nothing here is written by the AI, so nothing can be made up."), width=width + 4))
    names = docmod.list_collections()
    if not names:
        print(tr("\nThere is nothing to search on this computer yet."))
        if _offer_the_packs(docmod, width):
            names = docmod.list_collections()
        if not names:
            _doc_more_hints()
            return 1
    from . import pack as packmod
    found = [(name, packmod.manifest_of(name)) for name in names]
    packs = [(name, m) for name, m in found if m]
    own = [name for name, m in found if not m]
    if packs:
        print(tr("\nSearching the following Knowledge Packs:"))
        for name, m in packs:
            print(f"  {name:<18} {m.get('title')}")
        langs = set()
        for _name, m in packs:
            langs.update(str(x).lower() for x in (m.get("languages") or []))
        if langs and langs <= {"en", "eng", "english"}:
            print(tr("The packs on this computer are in English."))
    if own:
        # not everything indexed is a pack: these are the person's own files
        print(tr("\nAlso searching your own documents:  {names}").format(names=", ".join(own)))
    if packs:
        # Nothing updates a pack by itself, so the place a person meets their
        # packs is where they learn a newer version exists.
        from . import packbrowse
        notice = packbrowse.update_notice(packbrowse.outdated())
        if notice:
            print("\n" + notice)
    _doc_more_hints()
    if not first:
        print(tr("\nType a question, or press Enter on an empty line to finish."))
    asked = 0
    last_hits: list[dict] = []
    radius: dict[int, int] = {}       # how far each result has been opened so far
    told_about_reader = False
    pending = first
    while True:
        if pending is not None:
            question, pending = pending, None
        else:
            try:
                question = input(tr("\nQuestion: ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        if not question:
            break
        if question.isdigit() and 1 <= int(question) <= len(last_hits):
            n = int(question)
            if _doc_open_reader(last_hits[n - 1], docmod):
                print(tr("\nBack to your questions. Another number, or ask something else."))
                continue
            radius[n] = radius.get(n, 0) + 2
            if _doc_read_more(last_hits[n - 1], radius[n], docmod, width):
                print(tr("\nType {n} again for more of it, another number, or a new question.").format(n=n))
            if not told_about_reader and sys.stdin.isatty():
                told_about_reader = True
                print(tr("A reader that scrolls, searches and follows the window's width:  ai-2 install text-browser"))
            continue
        print()                       # the server's "Starting ..." line has its own line
        args.question = [question]
        hits = _doc_hits(args, docmod, hw, question, distinct=not args.doc)
        if hits is not None:
            asked += 1
            last_hits, radius = hits, {}
            _doc_show_hits(hits, width)
            print(tr("\nType a number to read more of that one, or ask something else."))
    print(tr("\nDone.") if asked else tr("\nNothing asked."))
    return 0


def _doc_ask(args, docmod) -> int:
    import functools
    from .chatterm import sentences, stream_reply
    from .sysinfo import mem_available_mib
    hw = detect()
    question = " ".join(args.question).strip()
    cfg = remote.load()
    if args.remote and cfg is None:
        print("error: no remote AI configured. Set one up with:  ai-2 remote set <url> [--api-key KEY]",
              file=sys.stderr)
        return 1
    hits = _doc_hits(args, docmod, hw, question)
    if hits is None:
        return 1
    score = load_score()
    if args.model:
        chat_model = runner._catalog_entry(args.model)
        if chat_model is None or chat_model.get("kind", "chat") != "chat":
            print(f"error: '{args.model}' is not a chat model in the catalog", file=sys.stderr)
            return 1
        if find_model_file(chat_model["file"]) is None:
            print(f"error: {chat_model['file']} is not downloaded. Run 'ai-2 model pull {chat_model['id']}'.",
                  file=sys.stderr)
            return 1
    else:
        present = [m["catalog"] for m in installed_models(load_catalog()) if m["id"]]
        chat_model = docmod.choose_answer_model(present, hw.ram_mib, score)
    messages = docmod.build_messages(question, hits)
    n_tokens = sum(docmod.estimate_tokens(m["content"]) for m in messages)
    est = docmod.prefill_seconds(n_tokens, score, chat_model)
    if args.remote:
        use_remote = True
    elif args.local or cfg is None:
        use_remote = False
    else:
        use_remote = bool(cfg.get("default")) or chat_model is None or is_starter(chat_model) \
            or (est is not None and est > docmod.SLOW_PREFILL_S)
    if use_remote:
        print(f"Asking {remote.describe(cfg)}. The question and the excerpts of your documents leave this computer.")
        stream = functools.partial(stream_reply, headers=remote.headers(cfg), model=cfg.get("model"),
                                   temperature=docmod.ANSWER_TEMPERATURE)
        base = cfg["url"]
    else:
        if chat_model is None:
            print("error: no chat model on this computer yet (ai-2 wizard), and no remote AI (ai-2 remote set).",
                  file=sys.stderr)
            return 1
        if est is not None and est > docmod.SLOW_PREFILL_S:
            print(f"Note: this computer may need up to {max(1, round(est / 60))} minute(s) to read the excerpts "
                  "before the first word of the answer. A remote AI would be faster:  ai-2 remote set <url>")
        if is_starter(chat_model):
            print(f"Note: {chat_model['label']} is a very small starter model; it can get facts wrong.")
        avail = mem_available_mib()
        if avail is not None and avail < int(chat_model.get("ram_peak_mb", 0)):
            serverstate.stop_server(name=serverstate.EMBED)   # make room, it restarts on demand
        base = runner._ensure_server(hw, chat_model, args.port, serverstate.CHAT, wait=args.wait)
        if base is None:
            return 1
        stream = functools.partial(stream_reply, temperature=docmod.ANSWER_TEMPERATURE)
    print()
    try:
        if args.stream:
            for piece in stream(base, messages):
                print(piece, end="", flush=True)
            print()
        else:
            for sentence in sentences(stream(base, messages)):
                print(sentence)
    except OSError as exc:
        print(f"error: the AI server went away ({exc}); run the command again", file=sys.stderr)
        return 1
    print("\nSources: " + "; ".join(f"[{i}] {h['cite']}" + (f" {h['url']}" if h.get("url") else "")
                                   for i, h in enumerate(hits, 1)))
    for line in _pack_terms(hits):
        print(line)
    return 0


def _mention_knowledge_packs() -> None:
    """After a successful update, one line for a machine that has no knowledge
    packs. An update changes packages, never a person's documents, so a machine
    brought up to date never gains the packs a fresh ISO install starts with,
    and nothing else tells it they exist. Nothing is downloaded here."""
    try:
        from . import pack, packbrowse
        if pack.installed_packs():
            # The update that just ran may have brought a newer copy of the
            # catalog; the file is read now, from disk, so this sees it.
            notice = packbrowse.update_notice(packbrowse.outdated())
            if notice:
                print("\n" + notice)
            return
        entries = pack.load_catalog()
    except Exception:                       # never let a hint break an update
        return
    if not entries:
        return
    names = ", ".join(e["id"] for e in entries[:3])
    print(f"\nThis computer has no knowledge packs. {len(entries)} can be installed and then searched with "
          f"no network at all ({names}).\nChoose among them in  Applications > AI-2 > Knowledge Packs , or with:  "
          "ai-2 knowledge browse\n"
          f"The community catalog, to get packs and to share one you made:  {pack.CATALOG_URL}")
