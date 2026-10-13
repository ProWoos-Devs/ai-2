"""Install for another owner: the person installing AI-2 is not always the
person who will use the computer (a relative's old PC, a refurbished one).
Taken from Omarchy, where the installer's first screen can be left without
personal details and the owner is asked at first boot.

Two halves, both `ai-2 owner-setup`:

* `--prepare` runs INSIDE the target during the install (the Calamares
  config /etc/calamares-owner on the stick has no Users page and runs it as
  a shellprocess job): a default hostname, a temporary account with no
  password that the login manager logs in by itself into the session
  /usr/share/xsessions/ai2-owner-setup.desktop, a sudo rule for exactly
  this command, and a marker that says the owner is still owed.

* without flags, as root, at the first boot in that session: a terminal
  window asks the owner's name, a login name, a password and the computer's
  name, creates the account the way the installer would have (same groups,
  sudo through wheel, root's password the same as the owner's, which is what
  the installer does when its "use the same password" box is ticked), then
  removes the temporary account, the autologin and the sudo rule, and
  restarts. The next login screen asks the owner for the password, and the
  usual first-login setup follows.

Everything the halves write is listed here so that the second can undo what
the first did; the temporary account has no password and can do nothing
but run this command."""

from __future__ import annotations

import os
import re
import subprocess
import time

TEMP_USER = "ai2-owner-setup"
TEMP_HOME = "/var/lib/ai2-owner-setup"
SESSION = "ai2-owner-setup"                      # /usr/share/xsessions/<SESSION>.desktop
PENDING = "/etc/ai2/owner-setup-pending"
SUDOERS = "/etc/sudoers.d/ai2-owner-setup"
LIGHTDM_CONF = "/etc/lightdm/lightdm.conf"
BLOCK_BEGIN = "# AI-2 owner setup: log the temporary account in until the owner has one"
BLOCK_END = "# AI-2 owner setup end"
DEFAULT_HOSTNAME = "ai2-pc"
# The groups Artix's installer gives the first user (its users.conf on the
# stick, 2026-10-13); the ones that do not exist here are skipped.
GROUPS = ["users", "lp", "video", "network", "storage", "wheel", "audio", "power", "log",
          "optical", "scanner"]
LOGIN_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")
HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
MIN_PASSWORD = 4                                  # the installer's own minimum


def _path(root: str, path: str) -> str:
    return os.path.join(root, path.lstrip("/"))


def pending(root: str = "/") -> bool:
    return os.path.exists(_path(root, PENDING))


# --- phase 1: inside the target, during the install -------------------------

def _write_hostname(root: str, name: str) -> None:
    with open(_path(root, "/etc/hostname"), "w") as fh:
        fh.write(name + "\n")
    hosts = _path(root, "/etc/hosts")
    try:
        with open(hosts) as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = ["127.0.0.1  localhost", "::1        localhost"]
    lines = [l for l in lines if not l.startswith("127.0.1.1")]
    lines.append(f"127.0.1.1  {name}")
    with open(hosts, "w") as fh:
        fh.write("\n".join(lines) + "\n")


NM_DIR = "/etc/NetworkManager/system-connections"


def _open_live_connections(root: str) -> int:
    """The installer copies the live session's network connections into the
    target and rewrites their `permissions=user:ai-2:;` line to the new
    user's name; with no Users page that name is "None", which no one can
    use. Open those to every user, so the WiFi the installer connected to
    is there for the owner. Returns how many files were changed."""
    changed = 0
    try:
        names = os.listdir(_path(root, NM_DIR))
    except OSError:
        return 0
    for name in names:
        path = os.path.join(_path(root, NM_DIR), name)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if "permissions=user:None:;" not in text:
            continue
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace("permissions=user:None:;", "permissions="))
        changed += 1
    return changed


def prepare(root: str = "/", run=subprocess.run, say=print) -> int:
    """What the install leaves behind so that the first boot asks the owner."""
    os.makedirs(_path(root, "/etc/ai2"), exist_ok=True)
    _open_live_connections(root)
    os.makedirs(_path(root, "/etc/sudoers.d"), exist_ok=True)
    os.makedirs(_path(root, "/etc/lightdm"), exist_ok=True)
    _write_hostname(root, DEFAULT_HOSTNAME)
    # the login manager's autologin PAM stack admits only the autologin group
    for cmd in (["groupadd", "-f", "autologin"],
                ["useradd", "-m", "-d", TEMP_HOME, "-s", "/bin/sh", "-G", "autologin",
                 "-c", "AI-2 owner setup", TEMP_USER]):
        proc = run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            say(f"owner setup: {' '.join(cmd)} failed: {(proc.stderr or '').strip()}")
            return 1
    with open(_path(root, SUDOERS), "w") as fh:
        fh.write(f"# AI-2: the temporary account may run the owner setup, nothing else\n"
                 f"{TEMP_USER} ALL=(root) NOPASSWD: /usr/bin/ai-2 owner-setup\n")
    os.chmod(_path(root, SUDOERS), 0o440)
    conf = _path(root, LIGHTDM_CONF)
    try:
        with open(conf) as fh:
            text = fh.read()
    except OSError:
        text = ""
    if not text.endswith("\n") and text:
        text += "\n"
    text += (f"\n{BLOCK_BEGIN}\n[Seat:*]\nautologin-user={TEMP_USER}\n"
             f"autologin-session={SESSION}\nautologin-user-timeout=0\n{BLOCK_END}\n")
    with open(conf, "w") as fh:
        fh.write(text)
    with open(_path(root, PENDING), "w") as fh:
        fh.write(f"prepared {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    say("owner setup: the first boot will ask for the owner's name and password")
    return 0


# --- phase 2: the first boot --------------------------------------------------

def _system_lang() -> None:
    """sudo drops LANG; take the installer's choice from /etc/locale.conf."""
    if os.environ.get("LANG"):
        return
    try:
        with open("/etc/locale.conf") as fh:
            for line in fh:
                if line.startswith("LANG="):
                    os.environ["LANG"] = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass


def suggest_login(name: str) -> str:
    """A login name from the owner's name: the first word, lowercase, ASCII
    letters and digits only."""
    import unicodedata
    first = (name.strip().split() or [""])[0]
    plain = unicodedata.normalize("NFKD", first).encode("ascii", "ignore").decode().lower()
    plain = re.sub(r"[^a-z0-9]", "", plain)
    if not plain or not plain[0].isalpha():
        plain = "user" + plain
    return plain[:32]


def suggest_hostname(login: str) -> str:
    return f"{login}-pc" if HOST_RE.match(f"{login}-pc") else DEFAULT_HOSTNAME


def user_exists(login: str, run=subprocess.run) -> bool:
    try:
        return run(["getent", "passwd", login], capture_output=True, text=True).returncode == 0
    except OSError:
        return False


def existing_groups(run=subprocess.run) -> list[str]:
    try:
        out = run(["getent", "group", *GROUPS], capture_output=True, text=True).stdout
    except OSError:
        return []
    have = {line.split(":")[0] for line in out.splitlines() if ":" in line}
    return [g for g in GROUPS if g in have]


def finish(root: str = "/", run=subprocess.run) -> None:
    """Undo what prepare() left: the autologin block, the sudo rule, the
    marker, the temporary account and its home."""
    conf = _path(root, LIGHTDM_CONF)
    try:
        with open(conf) as fh:
            text = fh.read()
        start, end = text.find(BLOCK_BEGIN), text.find(BLOCK_END)
        if start != -1 and end != -1:
            text = text[:start].rstrip("\n") + "\n" + text[end + len(BLOCK_END):].lstrip("\n")
            with open(conf, "w") as fh:
                fh.write(text)
    except OSError:
        pass
    for path in (SUDOERS, PENDING):
        try:
            os.remove(_path(root, path))
        except OSError:
            pass
    # -f: the account is the one this very session runs as
    run(["userdel", "-r", "-f", TEMP_USER], capture_output=True, text=True)


def run_setup(ask=input, secret=None, say=print, run=subprocess.run, root: str = "/",
              reboot: bool = True, sleep=time.sleep) -> int:
    """The questions, the account, the cleanup, the restart."""
    import getpass
    from .i18n import tr
    secret = secret or getpass.getpass
    if not pending(root):
        say(tr("This computer was not installed for another owner, so there is nothing to set up here."))
        say(tr("To add an account:  sudo useradd -m -G wheel NAME  and  sudo passwd NAME"))
        return 1
    say(tr("Welcome. This computer was prepared for you; a few answers and it is yours."))
    say("")
    while True:
        name = ask(tr("Your name, as the login screen should show it: ")).strip()
        if name:
            break
    default_login = suggest_login(name)
    while True:
        login = ask(tr("Login name [{default}]: ").format(default=default_login)).strip() or default_login
        if login == "root" or not LOGIN_RE.match(login):
            say(tr("A login name has only lowercase letters, digits, - and _, and starts with a letter."))
        elif user_exists(login, run):
            say(tr("That name is already taken on this computer."))
        else:
            break
    while True:
        password = secret(tr("Password (also used for administrator tasks; nothing shows while you type): "))
        if len(password) < MIN_PASSWORD:
            say(tr("At least {n} characters, please.").format(n=MIN_PASSWORD))
            continue
        if secret(tr("The same password again: ")) != password:
            say(tr("They do not match; once more."))
            continue
        break
    default_host = suggest_hostname(login)
    while True:
        host = ask(tr("This computer's name on the network [{default}]: ").format(default=default_host)).strip() or default_host
        if HOST_RE.match(host) and host != "localhost":
            break
        say(tr("Letters, digits and - only, starting and ending with a letter or digit."))
    say("")
    groups = existing_groups(run)
    cmd = ["useradd", "-m", "-U", "-s", "/bin/bash", "-c", name]
    if groups:
        cmd += ["-G", ",".join(groups)]
    cmd.append(login)
    proc = run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        say(tr("Creating the account failed: {error}").format(error=(proc.stderr or "").strip()))
        return 1
    proc = run(["chpasswd"], input=f"{login}:{password}\nroot:{password}\n", capture_output=True, text=True)
    if proc.returncode != 0:
        say(tr("Setting the password failed: {error}").format(error=(proc.stderr or "").strip()))
        return 1
    _write_hostname(root, host)
    run(["hostname", host], capture_output=True, text=True)
    finish(root, run)
    say(tr("Done, {name}. The computer restarts now; log in with your password, and the AI-2 setup starts.").format(name=name))
    if reboot:
        sleep(6)
        run(["reboot"])
    return 0
