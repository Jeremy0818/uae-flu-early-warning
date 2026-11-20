"""Quick sanity check: cross-correlation of Trends series vs FluNet SENTINEL positivity at weekly lags."""
import sys

import pandas as pd

sys.stdout.reconfigure(encoding="utf-8")

fn = pd.read_csv("data/raw/flunet/flunet_ARE.csv", low_memory=False)
fn = fn[fn.ORIGIN_SOURCE == "SENTINEL"].copy()
fn["wk"] = pd.to_datetime(fn.ISO_WEEKSTARTDATE)  # Monday
fn["pos"] = fn.INF_A.fillna(0) + fn.INF_B.fillna(0)
lab = fn.groupby("wk").agg(pos=("pos", "sum"), spec=("SPEC_PROCESSED_NB", "sum"))
lab["posrate"] = lab.pos / lab.spec
lab = lab[(lab.index >= "2022-01-01") & (lab.spec >= 20)]

out = []
for name in ["terms_AE", "topics_AE", "topics_AE-AZ"]:
    tr = pd.read_csv(f"data/interim/trends_{name}.csv", parse_dates=["week_start"])
    tr = tr[tr.is_partial == 0]
    tr["wk"] = tr.week_start + pd.Timedelta(days=1)  # Sunday -> Monday of same ISO week
    tr = tr.set_index("wk").drop(columns=["week_start", "is_partial"])
    for col in tr.columns:
        x = tr[col].rolling(3, center=False).mean()
        row = {"set": name, "col": col}
        for lag in [-2, -1, 0, 1, 2, 3]:  # positive lag: search leads lab by `lag` weeks
            j = pd.concat([x.shift(lag), lab.posrate], axis=1, join="inner").dropna()
            # correlate week-over-week changes too (less seasonality-driven)
            row[f"r{lag:+d}"] = round(j.iloc[:, 0].corr(j.iloc[:, 1]), 2)
        out.append(row)
print(pd.DataFrame(out).to_string(index=False))
print("lab weeks", len(lab), lab.index.min().date(), lab.index.max().date())
