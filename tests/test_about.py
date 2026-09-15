"""ai-2 about: the five lines, and that the base line never claims Artix
where it is not."""
import pathlib

from ai2 import __version__, about, cli

AI2_OS_RELEASE = pathlib.Path("iso/profiles/ai2/root-overlay/etc/os-release")


def test_ai2_image_reads_as_artix_with_its_init(tmp_path):
    values = about.read_os_release(str(AI2_OS_RELEASE))
    assert values["ID"] == "ai2"
    assert about.base_system(values, "runit") == "Artix Linux (runit)"


def test_plain_artix_install_with_the_package():
    assert about.base_system({"ID": "artix", "NAME": "Artix Linux"}, "openrc") == "Artix Linux (openrc)"


def test_other_systems_show_their_own_name():
    values = {"ID": "manjaro", "ID_LIKE": "arch", "PRETTY_NAME": "Manjaro Linux"}
    assert about.base_system(values, "systemd") == "Manjaro Linux (systemd)"


def test_missing_os_release_and_unknown_init(tmp_path):
    values = about.read_os_release(str(tmp_path / "absent"))
    assert values == {}
    assert about.base_system(values, "unknown") == "unknown"


def test_the_five_lines_in_order():
    lines = about.about_lines(os_release={"ID": "ai2", "ID_LIKE": "artix arch"},
                              init_system="runit", score={"ai_score": 29})
    assert lines == [
        ("Version", __version__),
        ("Based on", "Artix Linux (runit)"),
        ("AI Score", "29/100"),
        ("Website", "https://prowoos.com/software-development/linux/ai-2/"),
        ("License", "MIT"),
    ]


def test_no_score_yet_says_how_to_measure():
    assert about.score_text(None) == "not measured yet (run: ai-2 benchmark)"
    assert about.score_text({"tg_tps": 2.0}) == "not measured yet (run: ai-2 benchmark)"


def test_render_aligns_the_values():
    text = about.render([("Version", "1"), ("AI Score", "2/100")])
    assert text.splitlines() == ["Version   1", "AI Score  2/100"]


def test_cli_about_wait_returns_on_end_of_input(monkeypatch, capsys):
    monkeypatch.setattr(about, "read_os_release", lambda path=about.OS_RELEASE: {"ID": "artix"})
    monkeypatch.setattr(about, "detect_init_system", lambda: "runit")
    monkeypatch.setattr(about, "load_score", lambda: {"ai_score": 23})

    def no_input(prompt=""):
        print(prompt, end="")
        raise EOFError

    monkeypatch.setattr("builtins.input", no_input)
    assert cli.main(["about", "--wait"]) == 0
    out = capsys.readouterr().out
    assert "Artix Linux (runit)" in out
    assert "23/100" in out
    assert out.rstrip().endswith("Press Enter to close this window.")


def test_window_uses_the_wizards_terminals_in_order():
    have = {"xterm", "x-terminal-emulator", "xfce4-terminal"}
    cmd = about.window_command(which=lambda name: name in have)
    assert cmd == ["xfce4-terminal", "--title=About AI-2", "--geometry=70x13", "--hide-menubar",
                   "-x", "ai-2", "about", "--wait"]
    have.discard("xfce4-terminal")
    assert about.window_command(which=lambda name: name in have)[:2] == ["x-terminal-emulator", "-e"]
    have.discard("x-terminal-emulator")
    assert about.window_command(which=lambda name: name in have)[:3] == ["xterm", "-T", "About AI-2"]
    assert about.window_command(which=lambda name: False) is None


def test_cli_window_without_a_terminal_prints_instead(monkeypatch, capsys):
    monkeypatch.setattr(about, "window_command", lambda which=None: None)
    monkeypatch.setattr(about, "read_os_release", lambda path=about.OS_RELEASE: {})
    monkeypatch.setattr(about, "detect_init_system", lambda: "unknown")
    monkeypatch.setattr(about, "load_score", lambda: None)
    assert cli.main(["about", "--window"]) == 0
    captured = capsys.readouterr()
    assert "No terminal program found" in captured.err
    assert "License   MIT" in captured.out
