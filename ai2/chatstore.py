"""Conversations kept on this computer, one small JSON file each, private to the
account. Only what the person wrote and the model answered, and only exchanges
that finished. A file that cannot be written or read never stops a chat."""

from __future__ import annotations

import json
import os
import re
import time

KEY = re.compile(r"^[0-9a-f]{16}$")


def default_dir() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "ai2", "chats")


class Store:
    def __init__(self, directory: str | None = None):
        self.dir = directory or default_dir()

    def _path(self, key: str) -> str | None:
        return os.path.join(self.dir, key + ".json") if KEY.match(key or "") else None

    def save(self, key: str, messages: list[dict]) -> bool:
        path = self._path(key)
        if path is None:
            return False
        tmp = path + ".tmp"
        try:
            os.makedirs(self.dir, mode=0o700, exist_ok=True)
            created = (self._read(path) or {}).get("created") or time.time()
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"created": created, "updated": time.time(), "messages": messages}, f, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except OSError as exc:
            print(f"Could not save this conversation ({exc}).", flush=True)
            return False

    @staticmethod
    def _read(path: str) -> dict | None:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        messages = data.get("messages") if isinstance(data, dict) else None
        if not isinstance(messages, list) or not all(
                isinstance(m, dict) and isinstance(m.get("role"), str) and isinstance(m.get("content"), str)
                for m in messages):
            return None
        return data

    def load(self, key: str) -> list[dict] | None:
        path = self._path(key)
        data = self._read(path) if path else None
        return data["messages"] if data else None

    def keys(self) -> list[str]:
        try:
            names = os.listdir(self.dir)
        except OSError:
            return []
        return [n[:-5] for n in names if n.endswith(".json") and KEY.match(n[:-5])]

    def listing(self) -> list[dict]:
        """Newest first: key, when it was last used, and the first question."""
        out = []
        for key in self.keys():
            data = self._read(self._path(key))
            if data is None:
                continue
            first = next((m["content"] for m in data["messages"] if m["role"] == "user"), "")
            out.append({"key": key, "updated": float(data.get("updated") or 0), "first": first})
        return sorted(out, key=lambda c: c["updated"], reverse=True)

    def delete(self, key: str) -> bool:
        path = self._path(key)
        if path is None:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def delete_all(self) -> None:
        for key in self.keys():
            self.delete(key)
