#!/usr/bin/env python3
"""Watch the stable releases of the two engines AI-2 packages and propose a pin
bump as a pull request, one branch and one PR per engine.

    engine-watch.py check            which engine has a newer stable release (read-only)
    engine-watch.py update [--dry-run] [--run-tests]
                                     open or update the PR of every engine that has one

Run daily by .github/workflows/engine-watch.yml in the workspace repo. A PR is
only an alert with the version bump in it. Nothing reaches users until the
package is built, passes the ISA gates and the RMM-PC check, and is signed and
published by hand, as for every engine bump so far.

Stable means the release GitHub marks as latest (/releases/latest). For
llama.cpp that skips the nightly b-tags, which are prereleases since v1.0.0.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent          # the ai-2 tree (www/ai-2 in the workspace)
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"
BASE = "main"
BODY_LIMIT = 60000                                     # GitHub refuses PR bodies over 65536 characters
NOTES_LIMIT = 30000
HINT_LINES = 60

ENGINES = {
    "llama-cpp": {
        "package": "ai2-llama-cpp",
        "repo": "ggml-org/llama.cpp",
        "pkgbuild": "packaging/ai2-llama-cpp/PKGBUILD",
        "branch": "engine/llama-cpp",
        # files whose engine command-line flags the release notes are searched for
        "flag_sources": ["ai2/runtime.py", "ai2/persona.py"],
        "checks": [
            "Search quality: replay the 270 questions on the x64 (plain SSE2) variant, the one RMM-PC runs, and compare the decisions with the pinned build.",
            "Search cutoffs: `CHAT_MATCH` (0.45) in `ai2/gopher.py` and `ROUNDING_MARGIN` (0.003) in `ai2/packsig.py` still hold on the new vectors.",
            "Memory: `ram_peak_mb` in `ai2/data/models.yml` for the models measured on the new build.",
            "Speed: `ai-2 benchmark` (AI Score) on RMM-PC against the pinned build.",
        ],
    },
    "whisper-cpp": {
        "package": "ai2-whisper-cpp",
        "repo": "ggml-org/whisper.cpp",
        "pkgbuild": "packaging/ai2-whisper-cpp/PKGBUILD",
        "branch": "engine/whisper-cpp",
        "flag_sources": ["ai2/speech.py"],
        "checks": [
            "Transcription: `ai-2 transcribe` of the same recording on RMM-PC, text and time against the pinned build.",
            "The whisper-cli flags in `ai2/speech.py` are still accepted.",
        ],
    },
}

TAG_RE = re.compile(r"^([vb])(\d+(?:\.\d+)*)$")
HINT_RE = re.compile(r"\b(avx\w*|sse\w*|ssse3|f16c|fma|x86\w*|x64|cpu\w*|ggml-cpu\w*|remov\w*|deprecat\w*|"
                     r"break\w*|drop\w*|renam\w*|gguf)\b", re.I)
FLAG_LITERAL_RE = re.compile(r"""["'](-{1,2}[A-Za-z][A-Za-z0-9-]*)(?=["'=])""")
SELF = {"tools/engine-watch.py", "tests/test_engine_watch.py"}


class WatchError(Exception):
    pass


# ---------------------------------------------------------------- versions

def parse_tag(tag):
    """'v1.0.0' -> ('v', (1, 0, 0)); 'b10398' -> ('b', (10398,)). Anything else is refused."""
    m = TAG_RE.match(tag or "")
    if not m:
        raise WatchError(f"unexpected tag format {tag!r} (expected v1.2.3 or b12345)")
    return m.group(1), tuple(int(x) for x in m.group(2).split("."))


def read_pins(text):
    """The pin of an engine PKGBUILD: _tag, the prefix pkgver strips, pkgrel, epoch."""
    def one(pattern, what):
        found = re.findall(pattern, text, re.M)
        if len(found) != 1:
            raise WatchError(f"PKGBUILD: expected one {what} line, found {len(found)}")
        return found[0]
    tag = one(r"^_tag=(\S+)$", "_tag=")
    strip = one(r"^pkgver=\$\{_tag#([vb])\}$", "pkgver=${_tag#v} or ${_tag#b}")
    if not tag.startswith(strip):
        raise WatchError(f"PKGBUILD: pkgver strips {strip!r} but _tag is {tag!r}")
    parse_tag(tag)
    rel = int(one(r"^pkgrel=(\d+)$", "pkgrel="))
    epochs = re.findall(r"^epoch=(\d+)$", text, re.M)
    if len(epochs) > 1:
        raise WatchError("PKGBUILD: more than one epoch= line")
    return {"tag": tag, "strip": strip, "pkgrel": rel, "epoch": int(epochs[0]) if epochs else 0}


def version_string(pins):
    ver = pins["tag"][1:]
    return f"{pins['epoch']}:{ver}-{pins['pkgrel']}" if pins["epoch"] else f"{ver}-{pins['pkgrel']}"


def is_newer(old_tag, new_tag):
    """By number, and only within one tag scheme (b-numbers or v-versions)."""
    (po, vo), (pn, vn) = parse_tag(old_tag), parse_tag(new_tag)
    if po != pn:
        raise WatchError(f"cannot order {old_tag} and {new_tag}, they use different tag schemes")
    return vn > vo


def bump(text, new_tag):
    """The PKGBUILD pinned to new_tag: _tag and pkgrel=1. Only forward and only within the
    pin's tag scheme, so pacman always reads the new version as newer and no epoch is ever
    needed. An epoch would put a colon in the package file name, which GitHub renames on
    upload, and the [ai2] repository is a set of GitHub release assets."""
    old = read_pins(text)
    if not is_newer(old["tag"], new_tag):
        raise WatchError(f"{new_tag} is not newer than the pinned {old['tag']}")
    out = re.sub(r"^_tag=\S+$", f"_tag={new_tag}", text, count=1, flags=re.M)
    out = re.sub(r"^pkgrel=\d+$", "pkgrel=1", out, count=1, flags=re.M)
    new = read_pins(out)
    assert new["tag"] == new_tag and new["epoch"] == old["epoch"]
    return out, old, new


def pin_tag_for(release_tag, prefix, refs):
    """The tag in the pin's scheme at the commit of release_tag. llama.cpp's stable
    v1.0.0 is the same commit as its build tag b12359, and pinning b12359 keeps pacman's
    order (12359 after 10398) where 1.0.0 would sort before 10398."""
    if parse_tag(release_tag)[0] == prefix:
        return release_tag
    sha = refs.get(release_tag)
    if not sha:
        raise WatchError(f"tag {release_tag} not found upstream")
    same = [t for t, s in refs.items() if s == sha and TAG_RE.match(t) and t[0] == prefix]
    if not same:
        raise WatchError(f"no {prefix}-tag at the commit of {release_tag}; the pin's tag scheme needs a decision by hand")
    return max(same, key=lambda t: parse_tag(t)[1])


# ---------------------------------------------------------------- release notes

def flags_in(paths):
    """Command-line flags written as string literals in these source files."""
    found = set()
    for p in paths:
        found.update(FLAG_LITERAL_RE.findall((HERE / p).read_text()))
    return sorted(found)


def flag_lines(notes, flags):
    """Release-note lines that name one of these flags as a whole word."""
    pats = [(f, re.compile(r"(?<![\w-])" + re.escape(f) + r"(?![\w-])")) for f in flags]
    out = []
    for line in notes.splitlines():
        hit = [f for f, p in pats if p.search(line)]
        if hit:
            out.append((_item(line), hit))
    return out


def _item(line):
    """A release-note line without its own list marker, to sit in our list."""
    return re.sub(r"^\s*[-*+]\s+", "", line).strip()


def hint_lines(notes):
    return [_item(line) for line in notes.splitlines() if HINT_RE.search(line)]


def old_tag_mentions(tag):
    """file:line of every mention of the pinned tag in the ai-2 tree, CHANGELOG.md
    (history) and this tool left out, so comments and docstrings that name it get reviewed."""
    pat = re.compile(r"(?<![\w.])" + re.escape(tag) + r"(?![\w.])")
    hits = []
    for p in sorted(HERE.rglob("*")):
        rel = p.relative_to(HERE).as_posix()
        if not p.is_file() or rel == "CHANGELOG.md" or rel in SELF or any(part.startswith(".") or part == "__pycache__"
                                                           for part in p.relative_to(HERE).parts):
            continue
        if p.suffix not in {".py", ".sh", ".md", ".yml", ".yaml", ".txt", ".toml"} and p.name != "PKGBUILD":
            continue
        for n, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            if pat.search(line):
                hits.append(f"{rel}:{n}")
    return hits


def _limited(lines, limit, what):
    shown = lines[:limit]
    if len(lines) > limit:
        shown.append(f"... and {len(lines) - limit} more {what}, see the full release notes")
    return shown


def pr_title(cfg, release_tag, pin_to, old_tag):
    also = f" as {pin_to}" if pin_to != release_tag else ""
    return f"{cfg['package']}: {release_tag} is out{also} (pinned {old_tag})"


def pr_body(name, cfg, release, old, new, mentions, tests=None, run_url=None):
    notes = (release.get("body") or "").replace("\r\n", "\n")
    rel = release.get("tag_name") or new["tag"]
    url = release.get("html_url") or f"https://github.com/{cfg['repo']}/releases/tag/{rel}"
    flags = flag_lines(notes, flags_in(cfg["flag_sources"]))
    hints = hint_lines(notes)
    L = [f"{cfg['repo']} published **{rel}** on {(release.get('published_at') or '?')[:10]}. "
         f"{cfg['package']} is pinned to {old['tag']}.",
         "", f"Release notes: {url}", "",
         "This PR only moves the pin. Nothing reaches users until the package is built, gated and signed by hand.", "",
         "## What the commit changes", "",
         f"`{cfg['pkgbuild']}`: `_tag={new['tag']}`, `pkgrel=1`, "
         f"version {version_string(old)} to {version_string(new)}."]
    if rel != new["tag"]:
        L += ["", f"{rel} is tag {new['tag']}, the same commit. The pin keeps the {new['strip']}-tags, so pacman "
                  f"reads {version_string(new)} as newer than {version_string(old)} with no epoch. An epoch would "
                  "put a colon in the file name, which GitHub release assets do not keep."]
    L += ["", "## Before merging", "",
          f"- [ ] Build in the Artix container (`packaging/build-packages.sh {cfg['package']}`), with `isa-check.sh` passing in `check()`.",
          "- [ ] KVM guest without SSSE3, SSE4 or AVX: the engine runs and loads `libggml-cpu-x64.so`.",
          "- [ ] RMM-PC: install the unsigned candidate with `pacman -U` and compare with the pinned build."]
    L += [f"- [ ] {c}" for c in cfg["checks"]]
    L += ["- [ ] Comments and docs that name the old tag are updated or still true (list below).",
          "- [ ] CHANGELOG entry."]
    if tests is not None:
        L += ["", "## Unit tests on this branch", "",
              "The tests workflow does not start on a PR opened by GitHub Actions, so engine-watch ran the suite"
              + (f" ([run]({run_url}))" if run_url else "") + f": **{'passed' if tests['ok'] else 'FAILED'}**.",
              "", "```", tests["tail"], "```"]
    L += ["", f"## Release-note lines naming a flag AI-2 passes ({', '.join('`%s`' % s for s in cfg['flag_sources'])})", ""]
    L += [f"- {line}  (`{'`, `'.join(hit)}`)" for line, hit in flags] or ["None."]
    L += ["", "## Release-note lines about CPUs, x86, removals, renames and GGUF", "",
          "A keyword filter, not a review. Read the notes for anything it misses.", ""]
    L += [f"- {line}" for line in _limited(hints, HINT_LINES, "lines")] or ["None."]
    L += ["", f"## Mentions of {old['tag']} in the ai-2 tree", ""]
    L += [f"- `{m}`" for m in _limited(mentions, HINT_LINES, "mentions")] or ["None."]
    head = "\n".join(L)
    room = BODY_LIMIT - len(head) - 400
    cut = notes[:max(0, min(NOTES_LIMIT, room))]
    tail = ["", "<details><summary>Full release notes</summary>", "", cut]
    if len(cut) < len(notes):
        tail += ["", f"(cut at {len(cut)} of {len(notes)} characters, the rest is at {url})"]
    tail += ["", "</details>", "", "Opened by `.github/workflows/engine-watch.yml`."]
    return head + "\n" + "\n".join(tail)


# ---------------------------------------------------------------- GitHub and git

def api(path):
    req = urllib.request.Request(f"https://api.github.com/{path}",
                                 headers={"Accept": "application/vnd.github+json",
                                          "User-Agent": "ai2-engine-watch"})
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def run(*cmd, cwd=None, check=True, **kw):
    return subprocess.run(cmd, cwd=cwd or HERE, check=check, capture_output=True, text=True, **kw)


def tag_refs(repo):
    """Every upstream tag and the commit it points at, from one git ls-remote."""
    out, peeled = {}, {}
    for line in run("git", "ls-remote", "--tags", f"https://github.com/{repo}.git").stdout.splitlines():
        sha, ref = line.split("\t")
        name = ref.removeprefix("refs/tags/")
        if name.endswith("^{}"):
            peeled[name[:-3]] = sha
        else:
            out[name] = sha
    out.update(peeled)                                  # an annotated tag counts by its commit
    return out


def status(name, cfg, fetch=api, refs=tag_refs):
    """What the engine is pinned to, the latest stable release, the tag to pin for it in
    the pin's scheme, and whether that is newer."""
    pins = read_pins((HERE / cfg["pkgbuild"]).read_text())
    latest = fetch(f"repos/{cfg['repo']}/releases/latest")
    tag = latest["tag_name"]
    if latest.get("prerelease") or latest.get("draft"):
        raise WatchError(f"{cfg['repo']} marks the prerelease {tag} as latest")
    prefix = parse_tag(tag)[0]
    pin_to = tag if prefix == pins["strip"] else pin_tag_for(tag, pins["strip"], refs(cfg["repo"]))
    return {"engine": name, "pinned": pins["tag"], "latest": tag, "pin_to": pin_to,
            "published": latest.get("published_at"), "newer": is_newer(pins["tag"], pin_to), "release": latest}


def gh_json(*args):
    return json.loads(run("gh", *args).stdout or "null")


def run_tests():
    p = run(sys.executable, "-m", "pytest", "-q", "--tb=line", "-rfE", "tests/", check=False,
            env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"))
    lines = [s for s in (p.stdout + p.stderr).strip().splitlines()
             if not re.match(r"^[.sxXFE]+\s*\[\s*\d+%\]$", s)]        # the progress dots
    tail = "\n".join(lines[-30:])
    return {"ok": p.returncode == 0, "tail": tail}


def update(name, cfg, st, dry_run=False, with_tests=False, log=print):
    rel, tag, branch = st["latest"], st["pin_to"], cfg["branch"]
    prs = gh_json("pr", "list", "--head", branch, "--base", BASE, "--state", "all",
                  "--json", "number,state,title,url") or []
    open_pr = next((p for p in prs if p["state"] == "OPEN"), None)
    if any(p["state"] == "CLOSED" and p["title"].startswith(f"{cfg['package']}: {rel} ") for p in prs):
        log(f"{name}: {rel} was proposed before and the PR was closed without merging, leaving it")
        return "declined"
    top = run("git", "rev-parse", "--show-toplevel").stdout.strip()
    pkg = HERE / cfg["pkgbuild"]
    pkg_path = pkg.relative_to(top).as_posix()
    run("git", "fetch", "-q", "origin", f"+refs/heads/{BASE}:refs/remotes/origin/{BASE}", cwd=top)
    # the bump is made on main as it is now, never on the ref the workflow happened to start from
    main_pins = read_pins(run("git", "show", f"origin/{BASE}:{pkg_path}", cwd=top).stdout)
    if not is_newer(main_pins["tag"], tag):
        log(f"{name}: {BASE} already pins {main_pins['tag']}")
        return "current"
    title = pr_title(cfg, rel, tag, main_pins["tag"])
    remote = run("git", "ls-remote", "origin", f"refs/heads/{branch}").stdout.split()
    remote_sha = remote[0] if remote else None
    if remote_sha:
        run("git", "fetch", "-q", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}", cwd=top)
        pkg_on_branch = run("git", "show", f"origin/{branch}:{pkg_path}", cwd=top, check=False).stdout
        if open_pr and pkg_on_branch and read_pins(pkg_on_branch)["tag"] == tag:
            log(f"{name}: PR #{open_pr['number']} already proposes {tag}")
            return "proposed"
        authors = run("git", "log", "--format=%ae", f"origin/{BASE}..origin/{branch}", cwd=top).stdout.split()
        foreign = any(a != BOT_EMAIL for a in authors)
        if foreign and not open_pr and prs:
            # left over from a PR that was merged (squash and rebase merges leave the
            # branch's own commits outside main) or closed; GitHub keeps that PR's commits
            log(f"{name}: {branch} is left from PR #{prs[0]['number']} ({prs[0]['state'].lower()}), starting it again")
        elif foreign:
            msg = (f"{rel} is out. `{branch}` has commits that engine-watch did not make, so it was not "
                   f"moved. Rebase it on {tag} by hand, or delete the branch to let engine-watch start it again.")
            if not open_pr:
                raise WatchError(msg)                   # a branch without a PR: fail the run so someone looks
            marker = f"<!-- engine-watch {tag} -->"
            said = gh_json("pr", "view", str(open_pr["number"]), "--json", "comments")["comments"]
            if any(marker in c.get("body", "") for c in said):
                log(f"{name}: PR #{open_pr['number']} already told about {tag}")
            elif dry_run:
                log(f"{name}: would comment on PR #{open_pr['number']}: {msg}")
            else:
                run("gh", "pr", "comment", str(open_pr["number"]), "--body", f"{msg}\n\n{marker}")
                log(f"{name}: commented on PR #{open_pr['number']}")
            return "held"
    if dry_run:
        text, old, new = bump(run("git", "show", f"origin/{BASE}:{pkg_path}", cwd=top).stdout, tag)
        log(f"{name}: would push {branch} with {old['tag']} -> {tag} "
            f"({version_string(old)} -> {version_string(new)}) and "
            + (f"update PR #{open_pr['number']}" if open_pr else "open a PR") + f": {title}")
        return "dry-run"
    start = run("git", "rev-parse", "--abbrev-ref", "HEAD", cwd=top).stdout.strip()
    run("git", "checkout", "-q", "-B", branch, f"origin/{BASE}", cwd=top)
    try:
        text, old, new = bump(pkg.read_text(), tag)
        pkg.write_text(text)
        mentions = old_tag_mentions(old["tag"])           # on the branch, so not the new _tag= line
        tests = run_tests() if with_tests else None
        run("git", "add", str(pkg), cwd=top)
        run("git", "-c", f"user.name={BOT_NAME}", "-c", f"user.email={BOT_EMAIL}", "commit", "-q", "-m",
            f"{cfg['package']}: pin {tag} (was {old['tag']})\n\n"
            + (f"{tag} is the commit of the stable release {rel}.\n\n" if rel != tag else "") +
            "Proposed by engine-watch. Not built or gated yet.", cwd=top)
        lease = f"--force-with-lease=refs/heads/{branch}:{remote_sha or ''}"
        run("git", "push", "-q", lease, "origin", f"HEAD:refs/heads/{branch}", cwd=top)
    finally:
        run("git", "checkout", "-q", "-f", start, cwd=top, check=False)
    server, repo, run_id = (os.environ.get(k) for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    run_url = f"{server}/{repo}/actions/runs/{run_id}" if server and repo and run_id else None
    body = pr_body(name, cfg, st["release"], old, new, mentions, tests, run_url)
    body_file = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"engine-watch-{name}.md"
    body_file.write_text(body)
    if open_pr:
        run("gh", "pr", "edit", str(open_pr["number"]), "--title", title, "--body-file", str(body_file))
        log(f"{name}: updated PR #{open_pr['number']} to {tag}")
        return "updated"
    url = run("gh", "pr", "create", "--base", BASE, "--head", branch, "--title", title,
              "--body-file", str(body_file)).stdout.strip()
    log(f"{name}: opened {url}")
    return "opened"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="print pinned and latest stable release of each engine")
    up = sub.add_parser("update", help="open or update the PR of each engine with a newer release")
    up.add_argument("--dry-run", action="store_true", help="read only, say what would be done")
    up.add_argument("--run-tests", action="store_true", help="run the unit tests on the bumped tree")
    for p in sub.choices.values():
        p.add_argument("--engine", choices=sorted(ENGINES), help="only this engine")
    a = ap.parse_args(argv)
    failed = False
    for name, cfg in ENGINES.items():
        if a.engine and name != a.engine:
            continue
        try:
            st = status(name, cfg)
            also = f" = {st['pin_to']}" if st["pin_to"] != st["latest"] else ""
            print(f"{name}: pinned {st['pinned']}, latest stable {st['latest']}{also} "
                  f"({(st['published'] or '?')[:10]}), {'NEWER' if st['newer'] else 'up to date'}")
            if a.cmd == "update" and st["newer"]:
                update(name, cfg, st, dry_run=a.dry_run, with_tests=a.run_tests)
        except (WatchError, subprocess.CalledProcessError, OSError, KeyError, ValueError) as e:
            detail = getattr(e, "stderr", "") or ""
            print(f"::error::{name}: {e} {detail.strip()}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
