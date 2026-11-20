"""Parse compact Trends pulls (data/raw/trends/*.txt) into CSVs and verify against in-browser checksums.

Checksums come from the file's own '# checksum' line (pulls made with scripts/trends_pull.js);
the table below covers the original November 2026 pull, which predates that line.
"""
import json
import re
import sys
from pathlib import Path

import pandas as pd

# sum and index-weighted sum (1-based) per column, computed in the browser on the API response
CHECKSUMS = {
    "terms_AE": {"sum": [6102, 349, 12484, 809, 172], "wsum": [782093, 40110, 1554265, 97937, 20970]},
    "topics_AE": {"sum": [7702, 9943, 7884, 12930], "wsum": [1013678, 1234015, 940848, 1573550]},
    "topics_AE-AZ": {"sum": [8160, 10054, 8706, 14306], "wsum": [1078081, 1263331, 1044222, 1767794]},
    "emirates_AE": {"sum": [7692, 8089, 7607, 5581, 2928], "wsum": [1018395, 1063696, 1014916, 756764, 370930]},
}

root = Path(sys.argv[1] if len(sys.argv) > 1 else "data")
ok = True
for name, ck in CHECKSUMS.items():
    lines = (root / "raw/trends" / f"{name}.txt").read_text(encoding="utf-8").splitlines()
    header = lines[0]
    start = int(re.search(r"start_unix=(\d+)", header).group(1))
    cols = [c.strip() for c in next(l for l in lines if l.startswith("# cols:")).split(":", 1)[1].split("|")]
    ck_line = next((l for l in lines if l.startswith("# checksum")), None)
    if ck_line:
        s_, w_ = re.findall(r"sum=([\d,]+)", ck_line)
        ck = {"sum": [int(x) for x in s_.split(",")], "wsum": [int(x) for x in w_.split(",")]}
    toks = " ".join(l for l in lines if not l.startswith("#")).split()
    rows = [[int(v) for v in t.split(".")] for t in toks]
    assert all(len(r) == len(cols) for r in rows), name
    df = pd.DataFrame(rows, columns=cols)
    s = df.sum().tolist()
    w = (df.mul(pd.Series(range(1, len(df) + 1), index=df.index), axis=0)).sum().tolist()
    match = s == ck["sum"] and w == ck["wsum"]
    ok &= match
    df.insert(0, "week_start", pd.to_datetime(start + 604800 * pd.Series(range(len(df))), unit="s").dt.date)
    df["is_partial"] = 0
    if "Last row complete" not in header:
        df.loc[df.index[-1], "is_partial"] = 1
    out = root / "interim" / f"trends_{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8")
    print(name, "rows", len(df), df.week_start.iloc[0], "->", df.week_start.iloc[-1], "checksum", "OK" if match else f"MISMATCH sum={s} wsum={w}")
sys.exit(0 if ok else 1)
