"""The desktop menu: every AI-2 entry lives in one submenu, Applications >
AI-2, so the guides can name a single place and a user does not have to
guess between Accessories, Office and System (where the entries were
scattered before 0.9.0, and where a user looking for "AI-2 Chat" at the top
level found nothing)."""
import configparser
import pathlib
import xml.etree.ElementTree as ET

import pytest

DESKTOP = pathlib.Path("branding/desktop")
ENTRIES = ["ai2-chat", "ai2-chat-terminal", "ai2-guide", "ai2-software-updates", "ai2-about", "ai2-search"]
CATEGORY = "X-AI2"


def _entry(name):
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(DESKTOP / f"{name}.desktop", encoding="utf-8")
    return parser["Desktop Entry"]


def test_every_menu_entry_carries_only_the_ai2_category():
    for name in ENTRIES:
        categories = [c for c in _entry(name)["Categories"].split(";") if c]
        assert categories == [CATEGORY], f"{name}: {categories}"


def test_the_submenu_collects_that_category():
    root = ET.parse(DESKTOP / "ai2.menu").getroot()
    assert root.findtext("Name") == "Xfce", "must merge into xfce-applications.menu's root"
    sub = root.find("Menu")
    assert sub is not None and sub.findtext("Name") == "AI-2"
    assert sub.findtext("Directory") == "ai2.directory"
    assert sub.findtext("Include/Category") == CATEGORY


def test_about_ai2_opens_the_submenu():
    """Rafael, 2026-09-15: About AI-2 is the first entry of the AI-2 submenu,
    no separator. Checked with garcon 4.20 and in the QEMU install."""
    sub = ET.parse(DESKTOP / "ai2.menu").getroot().find("Menu")
    layout = [(child.tag, child.get("type") or (child.text or "").strip())
              for child in sub.find("Layout")]
    assert layout == [("Filename", "ai2-about.desktop"), ("Filename", "ai2-search.desktop"), ("Merge", "all")]


def _layout(element):
    return [(child.tag, child.get("type") or (child.text or "").strip())
            for child in element.find("Layout")]


def test_ai2_is_the_first_entry_of_the_applications_menu():
    """Rafael's placement, 2026-09-15: the AI-2 submenu at the very top, above
    Run Program, then a separator. Checked with garcon 4.20 against the real
    xfce-applications.menu and in the QEMU install."""
    layout = _layout(ET.parse(DESKTOP / "ai2.menu").getroot())
    assert layout[:3] == [("Menuname", "AI-2"), ("Separator", ""), ("Filename", "xfce4-run.desktop")]
    assert ("Merge", "all") in layout, "without it every other submenu disappears"
    assert layout.count(("Menuname", "AI-2")) == 1


def test_the_copied_layout_matches_the_installed_garcon_menu():
    """The merged Layout replaces XFCE's, so the rest of ours must stay the
    installed garcon's own layout. Runs where garcon's file exists (the
    developer laptop, an AI-2 system); skipped elsewhere."""
    installed = pathlib.Path("/etc/xdg/menus/xfce-applications.menu")
    if not installed.exists():
        pytest.skip("no xfce-applications.menu here")
    ours = _layout(ET.parse(DESKTOP / "ai2.menu").getroot())
    assert ours[2:] == _layout(ET.parse(installed).getroot())


def test_every_entry_is_installed_by_the_package():
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    for name in ENTRIES:
        assert f"/usr/share/applications/{name}.desktop" in pkgbuild, name


def test_about_ai2_opens_its_own_window():
    entry = _entry("ai2-about")
    assert entry["Exec"] == "ai-2 about --window"
    assert entry["Terminal"] == "false"


def test_the_submenu_has_a_directory_entry_with_the_ai2_icon():
    directory = configparser.ConfigParser(interpolation=None)
    directory.optionxform = str
    directory.read(DESKTOP / "ai2.directory", encoding="utf-8")
    section = directory["Desktop Entry"]
    assert section["Type"] == "Directory"
    assert section["Name"] == "AI-2"
    assert section["Icon"] == "ai2"


def test_the_package_installs_the_menu_where_garcon_reads_it():
    """garcon 4.20 merges xfce-applications.menu from applications-merged/,
    not xfce-applications-merged/ (checked with garcon itself: under the
    latter the entries fall into "Other")."""
    pkgbuild = pathlib.Path("packaging/ai-2/PKGBUILD").read_text(encoding="utf-8")
    assert "/etc/xdg/menus/applications-merged/ai2.menu" in pkgbuild
    assert "/usr/share/desktop-directories/ai2.directory" in pkgbuild
