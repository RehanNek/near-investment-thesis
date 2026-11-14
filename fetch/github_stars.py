"""GitHub: snapshot of NEAR AI's open-source repositories (developer adoption).

Lists every repository in the `nearai` GitHub organization with stars, forks, created and last
pushed dates. A star *history* isn't available: GitHub returns 404 for the stargazers list of
nearai/ironclaw (checked 2026-11-05), so each run saves a dated snapshot instead.

Needs the `gh` CLI logged in (or GITHUB_TOKEN in .env).

Output: data/raw/github/nearai_repos_<YYYY-MM-DD>.json

Usage: python -m fetch.github_stars
"""
from __future__ import annotations

import os
import subprocess

from fetch.common import RAW, http_get, load_env, record_fetch, utc_now, write_json

ORG = "nearai"


def token() -> str:
    load_env()
    if os.environ.get("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    return subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True).stdout.strip()


def main() -> None:
    headers = {"Authorization": f"Bearer {token()}", "Accept": "application/vnd.github+json"}
    repos, page = [], 1
    while True:
        batch = http_get(f"https://api.github.com/orgs/{ORG}/repos", params={"per_page": 100, "page": page},
                         headers=headers).json()
        repos += [{k: r.get(k) for k in ("full_name", "description", "stargazers_count", "forks_count",
                                         "created_at", "pushed_at", "archived")} for r in batch]
        if len(batch) < 100:
            break
        page += 1
    repos.sort(key=lambda r: -r["stargazers_count"])
    write_json(RAW / "github" / f"nearai_repos_{utc_now()[:10]}.json", repos)
    for r in repos[:5]:
        print(f"  {r['full_name']:36s} stars {r['stargazers_count']:6d}  forks {r['forks_count']:5d}  created {r['created_at'][:10]}")
    record_fetch("github_repos", org=ORG, repos=len(repos), top=repos[0]["full_name"] if repos else None)


if __name__ == "__main__":
    main()
