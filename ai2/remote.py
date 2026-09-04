"""A bigger AI somewhere else.

The benchmark is honest about old hardware: a score in the 20s means local
chat is a demo, and `ai-2 recommend` has said "use remote inference" since
the first release without anything behind the sentence. This is what is
behind it. A remote is any OpenAI-compatible endpoint: another computer in
the house running `ai-2 serve --host 0.0.0.0 --api-key KEY` (no account, no
key to buy), or an API provider the user has a key for. The old computer
then becomes the quiet, lean front end to a real model.

Nothing leaves the machine silently: a remote is used only when asked
(`ai-2 chat --remote`) or when the user made it the default with
`ai-2 remote set ... --default`, and every remote chat starts by saying
where the messages go. The key sits in ~/.config/ai2/remote.json, mode 600,
readable by the user alone."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .state import user_dir

PROBE_TIMEOUT_S = 15


def path() -> str:
    return os.path.join(user_dir(), "remote.json")


def normalize_url(url: str) -> str:
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if url.endswith("/v1"):
        url = url[:-3]
    return url


def load() -> dict | None:
    try:
        with open(path()) as fp:
            cfg = json.load(fp)
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict) or not cfg.get("url"):
        return None
    return cfg


def save(url: str, api_key: str | None = None, model: str | None = None,
         default: bool = False) -> str:
    cfg = {"url": normalize_url(url), "api_key": api_key or None,
           "model": model or None, "default": bool(default)}
    os.makedirs(user_dir(), mode=0o700, exist_ok=True)
    p = path()
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fp:
        json.dump(cfg, fp, indent=1)
        fp.write("\n")
    os.chmod(p, 0o600)   # an older file keeps its mode through O_CREAT
    return p


def set_default(default: bool) -> dict | None:
    cfg = load()
    if cfg is None:
        return None
    save(cfg["url"], cfg.get("api_key"), cfg.get("model"), default)
    return load()


def clear() -> bool:
    try:
        os.remove(path())
        return True
    except FileNotFoundError:
        return False


def headers(cfg: dict) -> dict:
    h = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        h["Authorization"] = "Bearer " + cfg["api_key"]
    return h


def masked_key(cfg: dict) -> str:
    key = cfg.get("api_key") or ""
    if not key:
        return "none"
    return "..." + key[-4:] if len(key) > 8 else "set"


def describe(cfg: dict) -> str:
    return cfg["url"] + (f" (model {cfg['model']})" if cfg.get("model") else "")


def _get_json(url: str, cfg: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers(cfg))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _pretty(model_id: str) -> str:
    """llama-server lists a model by its file path; show the file's name."""
    name = model_id.rsplit("/", 1)[-1]
    return name[:-5] if name.endswith(".gguf") else name


def _key_error(code: int) -> str:
    return f"HTTP {code}" + (" (wrong or missing API key)" if code in (401, 403) else "")


def probe(cfg: dict, timeout: float = PROBE_TIMEOUT_S) -> dict:
    """{'ok', 'models', 'web_ui', 'error'}: can we reach it with this key,
    which models does it list, and is it a llama-server (which has a chat
    page of its own the browser can open). llama-server answers /v1/models
    to anyone (its public list: /health, /models and the UI files, checked
    in the b10398 source) but gates /props behind the key, so a 401 there
    is the key check for that kind of remote."""
    out = {"ok": False, "models": [], "web_ui": False, "error": None}
    try:
        data = _get_json(cfg["url"] + "/v1/models", cfg, timeout)
        out["models"] = [_pretty(m.get("id", "")) for m in data.get("data", []) if isinstance(m, dict)]
    except urllib.error.HTTPError as exc:
        out["error"] = _key_error(exc.code)
        return out
    except (OSError, ValueError) as exc:
        out["error"] = str(exc)
        return out
    try:
        props = _get_json(cfg["url"] + "/props", cfg, timeout)
        out["web_ui"] = isinstance(props, dict)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            out["error"] = _key_error(exc.code)
            return out
    except (OSError, ValueError):
        pass
    out["ok"] = True
    return out
