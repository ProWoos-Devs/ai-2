#!/bin/bash
# AI-2: the manual lives in manual/ and the GitHub wiki is a copy of it.
#
# Until 2026-10-12 the wiki was edited in a clone of ai-2.wiki.git and the
# repository kept a copy that went stale (the idea of keeping the manual in
# the repository as the authoritative source is Omarchy's). Now a page change
# travels in the same commit as the code change it describes, the test suite
# checks every link between pages and every wiki address in the README and
# the code against the files here, and this script pushes manual/ to the wiki.
#
#   tools/wiki-sync.sh            push manual/ to the wiki (one commit, if anything differs)
#   tools/wiki-sync.sh --check    say whether the wiki matches manual/, push nothing (exit 1 if not)
#
# One file is one page: manual/Knowledge-Packs.md is the wiki page
# "Knowledge Packs". Pages deleted here are deleted there. The release
# checklist runs this after the package is published.
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
wiki_url=${AI2_WIKI_URL:-https://github.com/ProWoos-Devs/ai-2.wiki.git}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
git clone -q "$wiki_url" "$tmp/wiki"
if [[ "${1:-}" == --check ]]; then
    if diff -rq --exclude=.git "$here/manual" "$tmp/wiki"; then
        echo "The wiki matches manual/."
        exit 0
    fi
    echo "The wiki differs from manual/ (above). Push with:  tools/wiki-sync.sh"
    exit 1
fi
rsync -a --delete --exclude=.git "$here/manual/" "$tmp/wiki/"
cd "$tmp/wiki"
git add -A
if git diff --cached --quiet; then
    echo "The wiki already matches manual/; nothing to push."
    exit 0
fi
git diff --cached --stat
rev=$(git -C "$here" rev-parse --short HEAD)
git commit -q -m "Manual as of ai-2 $rev${1:+: $1}"
git push -q origin HEAD
echo "Pushed to the wiki."
