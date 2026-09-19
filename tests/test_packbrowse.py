"""Applications > AI-2 > Knowledge Packs: see the packs, pick by number,
install, and bring installed ones up to date. Driven with canned answers; the
download itself is a callable the window is given."""
import pytest

from ai2 import cli, pack, packbrowse, knowledgecli

CATALOG = [
    {"id": "ai2-help", "title": "AI-2 Help", "description": "AI-2's own documentation.", "parts": 107,
     "size_bytes": 346022, "languages": ["en"], "license": "MIT", "contact": "ProWoos-Devs", "revision": 2,
     "embedder": "nomic-embed-text-v1.5", "url": "https://x/a.ai2pack", "sha256": "0" * 64, "version": "2026-09-18"},
    {"id": "everyday", "title": "Everyday Reference", "description": "196 countries.", "parts": 196,
     "size_bytes": 593743, "languages": ["en"], "license": "CC0-1.0", "contact": "ProWoos-Devs", "revision": 3,
     "embedder": "nomic-embed-text-v1.5", "url": "https://x/e.ai2pack", "sha256": "1" * 64, "version": "2026-10-01"},
    {"id": "recipes", "title": "Family recipes", "parts": 12, "size_bytes": 2_400_000, "languages": ["es"],
     "license": "CC-BY-4.0", "contact": "someone", "revision": 1, "embedder": "nomic-embed-text-v2-moe",
     "url": "https://x/r.ai2pack", "sha256": "2" * 64, "version": "1"},
]


@pytest.fixture
def machine(monkeypatch):
    """ai2-help current, everyday one revision behind, recipes absent, and one
    pack of the person's own that no catalog knows."""
    state = {"ai2-help": {"id": "ai2-help", "title": "AI-2 Help", "revision": 2, "version": "2026-09-18"},
             "everyday": {"id": "everyday", "title": "Everyday Reference", "revision": 2, "version": "2026-09-18"},
             "mine": {"id": "my-notes", "title": "My notes", "revision": 1, "version": "1"}}
    monkeypatch.setattr(pack, "load_catalog", lambda: CATALOG)
    monkeypatch.setattr(pack, "installed_packs", lambda: sorted(state.items()))
    return state


def drive(answers, machine, cost=lambda e: None):
    said, asked, installs = [], [], []
    answers = list(answers)

    def ask(prompt):
        asked.append(prompt)
        return answers.pop(0)

    def install(entry):
        installs.append(entry["id"])
        machine[entry["id"]] = {"id": entry["id"], "title": entry["title"], "revision": entry["revision"]}
        return 0
    rc = packbrowse.browse(install, cost, ask=ask, say=said.append)
    return rc, "\n".join(said), asked, installs


def test_the_list_says_what_is_in_each_pack_who_made_it_and_where_it_stands(machine):
    rc, out, asked, installs = drive([""], machine)
    assert rc == 0 and installs == []
    assert "   1  ai2-help" in out and "[installed]" in out
    assert "[installed, newer version available]" in out.split("everyday")[1].split("\n")[0]
    assert "AI-2's own documentation." in out and "by ProWoos-Devs" in out and "by someone" in out
    assert "2.3 MB" in out and "337 KB" in out
    assert "Also installed here, from a file:  mine (My notes)" in out
    assert pack.CATALOG_URL in out and "ai-2 knowledge remove NAME" in out
    assert "type their numbers" in out and "type  u" in out and "Enter to close" in asked[0]
    assert all(len(line) <= 100 for line in out.split("\n")), "nothing wraps in the 100-column window"


def test_numbers_install_and_u_updates(machine):
    rc, out, asked, installs = drive(["3, 1", "u", ""], machine)
    assert installs == ["recipes", "everyday"], "1 was current and is skipped, u takes the outdated one"
    assert "ai2-help is already installed and up to date." in out
    assert "Every pack listed is installed and up to date" in asked[-1]


def test_the_model_cost_is_said_before_anything_is_fetched_and_no_means_no(machine):
    cost = lambda e: "Needs a 345 MB download, once." if e["id"] == "recipes" else None   # noqa: E731
    rc, out, asked, installs = drive(["3", "n", ""], machine, cost)
    assert "345 MB" in out and installs == [] and "Nothing installed." in out
    rc, out, asked, installs = drive(["3", "", ""], machine, cost)
    assert installs == ["recipes"]


def test_what_is_not_understood_is_said_and_a_failed_download_does_not_close_the_window(machine):
    def failing(entry):
        raise pack.PackError("the file does not match the catalog")
    said = []
    answers = iter(["9 x", "3", ""])
    rc = packbrowse.browse(failing, lambda e: None, ask=lambda p: next(answers), say=said.append)
    out = "\n".join(said)
    assert "Not understood: 9 x" in out and "error: recipes: the file does not match" in out
    assert rc == 1


def test_a_script_gets_the_list_and_no_question(machine):
    said = []
    rc = packbrowse.browse(lambda e: 0, lambda e: None, say=said.append, interactive=False,
                           ask=lambda p: pytest.fail("must not ask a script"))
    assert rc == 0 and "linux" not in "\n".join(said) and "everyday" in "\n".join(said)


def test_outdated_and_the_notice(machine):
    assert [e["id"] for e in packbrowse.outdated()] == ["everyday"]
    notice = packbrowse.update_notice(packbrowse.outdated())
    assert "A newer version is available for: Everyday Reference." in notice
    assert "Applications > AI-2 > Knowledge Packs" in notice and "ai-2 knowledge update" in notice
    assert packbrowse.update_notice([]) == ""


def test_knowledge_update_brings_installed_packs_up_to_date(machine, monkeypatch, capsys):
    done = []
    monkeypatch.setattr(knowledgecli, "_install_cataloged_pack", lambda entry, p, d: done.append(entry["id"]) or 0)
    assert cli.main(["knowledge", "update"]) == 0
    assert done == ["everyday"], "only what has a newer revision; never something not installed"
    machine["everyday"]["revision"] = 3
    done.clear()
    assert cli.main(["knowledge", "update"]) == 0 and done == []
    out = capsys.readouterr().out
    assert "newest version this AI-2 knows of" in out and "ai-2 update" in out
    assert cli.main(["knowledge", "update", "ai2-help"]) == 0
    assert "ai2-help: nothing newer" in capsys.readouterr().out


def test_the_end_of_ai2_update_says_when_a_pack_has_a_newer_version(machine, capsys):
    knowledgecli._mention_knowledge_packs()
    out = capsys.readouterr().out
    assert "Everyday Reference" in out and "Applications > AI-2 > Knowledge Packs" in out


def test_several_packs_install_in_one_command(machine, monkeypatch, capsys):
    got = []
    monkeypatch.setattr(knowledgecli, "_fetch_cataloged_pack", lambda entry, p, d: got.append(entry["id"]) or "/nonexistent")
    monkeypatch.setattr(pack, "install_pack", lambda *a, **k: (_ for _ in ()).throw(pack.PackError("stop here")))
    assert cli.main(["knowledge", "install", "ai2-help", "recipes"]) == 1
    assert got == ["ai2-help", "recipes"], "one that fails does not stop the next"
    assert cli.main(["knowledge", "install", "ai2-help", "recipes", "--as", "x"]) == 1
    assert "--as names one collection" in capsys.readouterr().err


def test_the_menu_entry_opens_a_window_big_enough_for_the_list(monkeypatch):
    """Terminal=true would give the terminal's default 80x24, where the top of
    the list scrolls away; the entry opens its own window like the setup does."""
    import configparser
    from ai2 import about
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read("branding/desktop/ai2-packs.desktop", encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Exec"] == "ai-2 knowledge browse --window" and entry["Terminal"] == "false"
    assert entry["Name"] == "Knowledge Packs"
    opened = []
    monkeypatch.setattr(about.subprocess, "Popen", lambda cmd, **k: opened.append(cmd))
    monkeypatch.setattr(about.shutil, "which", lambda name: "/usr/bin/" + name if name == "xfce4-terminal" else None)
    assert cli.main(["knowledge", "browse", "--window"]) == 0
    assert opened == [["xfce4-terminal", "--title=Knowledge Packs", "--geometry=100x38", "--hide-menubar",
                       "-x", "ai-2", "knowledge", "browse"]]
