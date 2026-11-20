"""Install a browser Trends pull (scripts/trends_pull.js output) into data/raw/trends/.

Each file is checked (header, columns, checksum line, row count) before anything is replaced.
Previous files are kept as *.prev.txt. Prints summary counts only.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data/raw/trends"
EXPECTED_COLS = {"topics_AE": 4, "topics_AE-AZ": 4, "terms_AE": 5, "emirates_AE": 5}


def check(name: str, text: str) -> int:
    lines = text.splitlines()
    assert re.search(r"start_unix=\d+ step=604800", lines[0]), f"{name}: bad header"
    cols = next(l for l in lines if l.startswith("# cols:")).split(":", 1)[1].split("|")
    assert len(cols) == EXPECTED_COLS[name], f"{name}: expected {EXPECTED_COLS[name]} columns, got {len(cols)}"
    ck = next(l for l in lines if l.startswith("# checksum"))
    sums = [list(map(int, x.split(","))) for x in re.findall(r"sum=([\d,]+)", ck)]
    rows = [[int(v) for v in t.split(".")] for t in " ".join(l for l in lines if not l.startswith("#")).split()]
    assert all(len(r) == len(cols) for r in rows), f"{name}: ragged rows"
    assert [sum(c) for c in zip(*rows)] == sums[0], f"{name}: checksum mismatch"
    if name == "emirates_AE":
        assert re.search(r"AE-UQ \d+, AE-FU \d+ of \d+", text), f"{name}: missing zero-week line"
    return len(rows)


def main(path: str) -> int:
    pull = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    files = pull["files"]
    missing = set(EXPECTED_COLS) - set(files)
    if missing:
        print("Trends pull is missing", sorted(missing))
        return 1
    try:
        counts = {n: check(n, files[n]) for n in EXPECTED_COLS}
    except (AssertionError, StopIteration, ValueError) as e:
        print("Trends pull rejected:", e)
        return 1
    for n in EXPECTED_COLS:
        dest = DIR / f"{n}.txt"
        if dest.exists():
            os.replace(dest, DIR / f"{n}.prev.txt")
        dest.write_text(files[n], encoding="utf-8")
    print("Trends pull", pull.get("pulled"), "installed:", counts)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1]))
