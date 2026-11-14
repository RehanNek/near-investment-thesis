"""Shared helpers for the data fetchers: paths, .env loading, HTTP, and a fetch manifest."""
from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
MANIFEST = RAW / "_manifest.json"
USER_AGENT = "near-thesis-research/0.1"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_env(path: Path = ROOT / ".env") -> None:
    """Load KEY=VALUE lines from .env into os.environ (existing variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require_env(name: str) -> str:
    load_env()
    value = os.environ.get(name, "")
    if not value:
        raise SystemExit(f"{name} is not set. Add it to .env (see .env.example).")
    return value


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def http_get(url: str, *, params=None, headers=None, timeout=60, retries=5, backoff=10.0):
    """GET with retries on 429/5xx and network errors. Returns the Response."""
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            print(f"  network error ({e.__class__.__name__}), retrying in {backoff:.0f}s")
            time.sleep(backoff)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            if attempt == retries - 1:
                r.raise_for_status()
            wait = backoff * (attempt + 1)
            print(f"  HTTP {r.status_code}, retrying in {wait:.0f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


def http_post_json(url: str, payload: dict, *, timeout=60, retries=5, backoff=5.0):
    for attempt in range(retries):
        try:
            r = _session.post(url, json=payload, timeout=timeout)
            if r.status_code == 429 or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError("unreachable")


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_jsonl_gz(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(path)


def record_fetch(source: str, **details) -> None:
    """Record what was fetched and when, for the appendix's sources-with-dates list."""
    manifest = read_json(MANIFEST, {})
    manifest[source] = {"fetched_at": utc_now(), **details}
    write_json(MANIFEST, manifest)
