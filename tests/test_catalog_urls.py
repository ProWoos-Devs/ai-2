"""Every catalog entry must match the file behind it. The network tests run only
when AI2_NET_TESTS=1 is set (CI's catalog job; offline runs skip them): Knowledge
Packs are small enough to download and hash, models are checked by size and by
the SHA-256 Hugging Face reports, without fetching gigabytes."""
import hashlib
import os
import pathlib
import re
import subprocess
import urllib.error
import urllib.request

import pytest

from ai2 import pack, speech
from ai2.models import load_catalog
from ai2.runtime import hf_url

net = pytest.mark.skipif(os.environ.get("AI2_NET_TESTS") != "1",
                         reason="set AI2_NET_TESTS=1 to check the catalogs online")
MODELS = load_catalog(kind=None) + speech.load_catalog()     # chat, embedding, speech
UA = {"User-Agent": "ai-2"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _hf_reported_sha256(url: str) -> str | None:
    """Hugging Face names an LFS file's SHA-256 on the redirect to its storage."""
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    try:
        resp = urllib.request.build_opener(_NoRedirect).open(req, timeout=30)
    except urllib.error.HTTPError as exc:      # the 302 arrives as an error here
        resp = exc
    return (resp.headers.get("X-Linked-Etag") or "").strip('"') or None


@net
@pytest.mark.parametrize("model", MODELS, ids=lambda m: m["id"])
def test_model_url_size_and_hash(model):
    req = urllib.request.Request(hf_url(model), method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        size_mb = int(r.headers.get("Content-Length") or 0) // (1 << 20)
    assert r.status == 200
    # file_mb is the size rounded up, never more than 5% off
    assert size_mb <= model["file_mb"] <= size_mb * 1.05 + 2
    assert _hf_reported_sha256(hf_url(model)) == model["sha256"]


@net
@pytest.mark.parametrize("entry", pack.load_catalog(), ids=lambda p: p["id"])
def test_knowledge_pack_url_size_and_hash(entry):
    with urllib.request.urlopen(urllib.request.Request(entry["url"], headers=UA), timeout=120) as r:
        body = r.read()
    assert len(body) == entry["size_bytes"]
    assert hashlib.sha256(body).hexdigest() == entry["sha256"]


def _change_filter() -> str:
    """The pattern the catalog job's change detector greps for."""
    workflow = pathlib.Path(".github/workflows/tests.yml").read_text()
    return re.search(r"grep -qxE '([^']+)'", workflow).group(1)


@pytest.mark.parametrize("path, runs", [
    ("ai2/data/models.yml", True),
    ("ai2/data/speech-models.yml", True),
    ("ai2/data/packs.yml", True),
    ("tests/test_catalog_urls.py", True),
    ("www/ai-2/ai2/data/packs.yml", False),     # not a path in the public repository
    ("ai2/doc.py", False),
])
def test_catalog_job_triggers_on_paths_of_the_public_repository(path, runs):
    if runs:
        assert pathlib.Path(path).exists(), f"{path} is not where the job looks"
    found = subprocess.run(["grep", "-qxE", _change_filter()], input=path, text=True).returncode == 0
    assert found is runs
