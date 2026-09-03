"""The desktop menu: every AI-2 entry lives in one submenu, Applications >
AI-2, so the guides can name a single place and a user does not have to
guess between Accessories, Office and System (where the entries were
scattered before 0.9.0, and where a user looking for "AI-2 Chat" at the top
level found nothing)."""
import configparser
import pathlib
import xml.etree.ElementTree as ET

DESKTOP = pathlib.Path("branding/desktop")
ENTRIES = ["ai2-chat", "ai2-chat-terminal", "ai2-guide", "ai2-software-updates"]
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
