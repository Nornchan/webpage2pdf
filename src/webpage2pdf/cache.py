"""
cache.py — remember what was fetched, so re-rendering costs nothing.

Converting the same article to a second format, or trying it against another
profile, used to re-download the page and every image. That makes tuning a
stylesheet or comparing presets slow enough that you stop doing it, which is the
real cost: the tool discourages the iteration it exists to support.

Entries are content-addressed by URL and stored under the platform cache
directory, so nothing here is precious — deleting it loses only time.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import time

# A page is worth re-fetching eventually; an image at a given URL almost never
# changes, so it gets a much longer life.
PAGE_TTL_SECONDS = 24 * 3600
ASSET_TTL_SECONDS = 30 * 24 * 3600


def default_dir() -> str:
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    elif sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, "webpage2pdf")


class Cache:
    """
    A tiny content-addressed store. Disabled instances are no-ops throughout,
    so callers never branch on whether caching is on.
    """

    def __init__(self, directory: str | None = None, *,
                 enabled: bool = True, refresh: bool = False):
        self.directory = directory or default_dir()
        self.enabled = enabled
        # refresh means "use the cache, but treat what is in it as stale", which
        # is what you want after a page has been updated.
        self.refresh = refresh
        self.hits = 0
        self.misses = 0

    # ---- internals -------------------------------------------------------

    def _path(self, kind: str, key: str, suffix: str = "") -> str:
        digest = hashlib.sha256(key.encode("utf-8", "ignore")).hexdigest()
        # Two-character shard, so a few thousand entries do not land in one
        # directory that every `ls` then has to enumerate.
        return os.path.join(self.directory, kind, digest[:2], digest[2:] + suffix)

    def _fresh(self, path: str, ttl: int) -> bool:
        if self.refresh or not os.path.isfile(path):
            return False
        try:
            return (time.time() - os.path.getmtime(path)) < ttl
        except OSError:
            return False

    @staticmethod
    def _write(path: str, data: bytes) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # Write then rename: a reader must never see a half-written entry, and
        # two conversions of the same URL can easily run at once.
        tmp = f"{path}.{os.getpid()}.part"
        try:
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    # ---- pages -----------------------------------------------------------

    def get_page(self, url: str) -> tuple[str, str] | None:
        """Returns (html, final_url) if a fresh copy is held."""
        if not self.enabled:
            return None
        body = self._path("pages", url, ".html")
        meta = self._path("pages", url, ".json")
        if not self._fresh(body, PAGE_TTL_SECONDS):
            return None
        try:
            with open(body, encoding="utf-8") as fh:
                html = fh.read()
            with open(meta, encoding="utf-8") as fh:
                final_url = json.load(fh).get("final_url", url)
        except (OSError, ValueError):
            return None
        self.hits += 1
        return html, final_url

    def put_page(self, url: str, html: str, final_url: str) -> None:
        if not self.enabled:
            return
        self.misses += 1
        self._write(self._path("pages", url, ".html"), html.encode("utf-8"))
        self._write(self._path("pages", url, ".json"),
                    json.dumps({"final_url": final_url, "url": url,
                                "fetched": time.time()}).encode("utf-8"))

    # ---- images ----------------------------------------------------------

    def get_asset(self, url: str) -> bytes | None:
        if not self.enabled:
            return None
        path = self._path("assets", url)
        if not self._fresh(path, ASSET_TTL_SECONDS):
            return None
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            return None
        self.hits += 1
        return data

    def put_asset(self, url: str, data: bytes) -> None:
        if not self.enabled:
            return
        self.misses += 1
        self._write(self._path("assets", url), data)

    # ---- housekeeping ----------------------------------------------------

    def stats(self) -> dict:
        pages = assets = 0
        size = 0
        for kind, counter in (("pages", "pages"), ("assets", "assets")):
            root = os.path.join(self.directory, kind)
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    if name.endswith(".json") or name.endswith(".part"):
                        continue
                    try:
                        size += os.path.getsize(os.path.join(dirpath, name))
                    except OSError:
                        continue
                    if kind == "pages":
                        pages += 1
                    else:
                        assets += 1
        return {"directory": self.directory, "pages": pages,
                "assets": assets, "bytes": size}

    def clear(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)
