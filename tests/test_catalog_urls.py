"""Every catalog model must be downloadable anonymously. Network test: runs
only when AI2_NET_TESTS=1 is set (CI/offline runs skip it)."""
import os
import urllib.request

import pytest

from ai2.models import load_catalog
from ai2.runtime import hf_url

pytestmark = pytest.mark.skipif(os.environ.get("AI2_NET_TESTS") != "1",
                                reason="set AI2_NET_TESTS=1 to check the model URLs online")


@pytest.mark.parametrize("model", load_catalog(), ids=lambda m: m["id"])
def test_catalog_url_is_public(model):
    req = urllib.request.Request(hf_url(model), method="HEAD", headers={"User-Agent": "ai-2"})
    with urllib.request.urlopen(req, timeout=30) as r:
        size_mb = int(r.headers.get("Content-Length") or 0) // (1 << 20)
    assert r.status == 200
    # file_mb is the size rounded up, never more than 5% off
    assert size_mb <= model["file_mb"] <= size_mb * 1.05 + 2
