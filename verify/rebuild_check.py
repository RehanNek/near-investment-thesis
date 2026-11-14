"""make check: rebuild everything from the raw data and confirm it matches the committed files.

Keeps a copy of every generated file in memory, deletes the files, runs `make charts` (data/raw/ ->
analysis/*.py -> data/derived/ -> viz/build.py -> the documents and charts), then compares each rebuilt file
with its copy. Deleting first means the rebuild can only use the raw data, the code and config.yaml.

  Documents and charts   THESIS.md, METHODS.md, DASHBOARD.md, site/index.html, site/charts/*.svg
                         must be identical byte for byte.
  Data files             data/derived/*.csv and headline_numbers.json must be identical, or differ only
                         beyond the 9th significant figure of a number. Sums of many floating-point
                         values can differ in the last digit from one processor to another; nothing
                         shown in a document or chart is printed to that precision.

Exit code: 0 if everything matches, 1 if anything differs (the first differing lines are printed).
The rebuilt files stay in place, so `git status` and `git diff` show the same thing. If the rebuild itself
stops with an error, the files are put back as they were.
Usage: python -m verify.rebuild_check
"""
from __future__ import annotations

import difflib
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["THESIS.md", "METHODS.md", "DASHBOARD.md", "site/index.html"]
REL_TOL = 1e-9
NUMBER = re.compile(r"-?\d+\.?\d*(?:[eE][-+]?\d+)?")


def rebuilt_by_make_charts(name: str) -> bool:
    """valuation_*.csv belong to an analysis that is no longer part of the build, so they are not checked."""
    return not name.startswith("valuation_")


def outputs() -> dict:
    """Every generated file, by kind."""
    return {
        "documents": [ROOT / p for p in DOCS],
        "charts": sorted((ROOT / "site" / "charts").glob("*.svg")),
        "data files": sorted(p for p in (ROOT / "data" / "derived").iterdir()
                             if p.suffix in (".csv", ".json") and rebuilt_by_make_charts(p.name)),
    }


def snapshot() -> dict:
    return {p: p.read_bytes() for paths in outputs().values() for p in paths}


def same_numbers(a: str, b: str) -> bool:
    """True if two texts differ only in numbers, and those agree to REL_TOL."""
    if NUMBER.sub("#", a) != NUMBER.sub("#", b):
        return False
    return all(math.isclose(float(x), float(y), rel_tol=REL_TOL, abs_tol=1e-12)
               for x, y in zip(NUMBER.findall(a), NUMBER.findall(b)))


def first_difference(before: str, after: str, name: str) -> str:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), f"{name} (committed)", f"{name} (rebuilt)",
                                lineterm="", n=0)
    return "\n".join(line[:200] for line in list(diff)[:8])


def restore(before: dict) -> None:
    for p, content in before.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)


def main() -> int:
    before = snapshot()
    make = os.environ.get("MAKE", "make")
    print(f"Deleted the {len(before)} generated files; rebuilding them from data/raw/ ({Path(make).name} charts) ...",
          flush=True)
    t0 = time.time()
    try:
        for p in before:
            p.unlink()
        run = subprocess.run([make, "--no-print-directory", "charts"], cwd=ROOT, capture_output=True, text=True)
    except BaseException:
        restore(before)
        raise
    if run.returncode != 0:
        restore(before)
        print(run.stdout[-3000:], run.stderr[-3000:], sep="\n")
        print("FAILED: the rebuild itself stopped with an error (above). The files were put back as they were.")
        return 1
    secs = time.time() - t0
    after = outputs()

    problems, close = [], []
    print(f"\n  {'Kind':<12}  {'Files':>5}  Result")
    for kind, paths in after.items():
        identical = 0
        for p in paths:
            name = str(p.relative_to(ROOT))
            new = p.read_bytes()
            if p not in before:
                problems.append(f"{name}: written by the rebuild, but not there before")
            elif new == before[p]:
                identical += 1
            elif kind == "data files" and same_numbers(before[p].decode(), new.decode()):
                close.append(name)
            else:
                problems.append(f"{name}: differs\n{first_difference(before[p].decode(), new.decode(), name)}")
        n_close = sum(1 for c in close if (ROOT / c) in paths)
        result = f"{identical} identical byte for byte"
        if n_close:
            result += f", {n_close} equal to 9 significant figures"
        if identical + n_close < len(paths):
            result += f", {len(paths) - identical - n_close} DIFFER"
        print(f"  {kind:<12}  {len(paths):>5}  {result}")
    for p in before:
        if not p.exists():
            problems.append(f"{p.relative_to(ROOT)}: was there before, not written by the rebuild")

    total = sum(len(v) for v in after.values())
    if problems:
        print("\n" + "\n\n".join(problems))
        print(f"\nDIFFERS: {len(problems)} of {total} files do not match the committed copy.")
        return 1
    if close:
        print("\n  Equal to 9 significant figures (last-digit floating-point differences): " + ", ".join(close))
    print(f"\nOK: all {total} generated files match the committed copies (rebuilt in {secs:.0f} s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
