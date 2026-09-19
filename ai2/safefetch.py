"""One rule for every download: HTTPS, and a redirect may not leave it.

Knowledge packs have had this since 0.18.0. Models are the bigger download by
far (44 MB to several GB, often on an old laptop's wifi), and they went over
a bare urlopen that followed a redirect to plain HTTP without a word. A
sha256 check afterwards proves the bytes were wrong, never that they were
private, so the rule belongs to both.
"""

from __future__ import annotations

import urllib.parse
import urllib.request


class UnsafeRedirect(Exception):
    """A download was redirected somewhere that is not HTTPS."""


def is_safe_url(url: str) -> bool:
    """HTTPS, or plain HTTP to this machine. A download to 127.0.0.1 crosses
    no network, so there is nobody to intercept it; that is what the tests
    and a local mirror use."""
    parsed = urllib.parse.urlparse(str(url))
    return parsed.scheme == "https" or (parsed.scheme == "http"
                                        and parsed.hostname in ("127.0.0.1", "localhost", "::1"))


class HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect may not leave HTTPS. Release assets redirect to a CDN, which
    is fine; a redirect to http would hand the bytes to anyone on the path."""

    error = UnsafeRedirect

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_safe_url(newurl):
            raise self.error(f"the download was redirected to {newurl.split(':')[0]}, which is not https")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def opener(*handlers) -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(HttpsOnlyRedirect, *handlers)
