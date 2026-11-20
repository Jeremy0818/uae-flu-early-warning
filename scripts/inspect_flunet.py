"""Summary-only inspection of FluNet CSV (prints stats, no raw rows)."""
import sys
import pandas as pd

path = sys.argv[1]
df = pd.read_csv(path, low_memory=False)
print("rows", len(df), "cols", len(df.columns))
print("columns:", list(df.columns))
for c in ["COUNTRY_CODE", "ORIGIN_SOURCE", "ISO_YEAR"]:
    if c in df.columns:
        print(c, df[c].value_counts(dropna=False).sort_index().to_dict())

date_col = next((c for c in ["ISO_WEEKSTARTDATE", "ISO_SDATE", "SDATE"] if c in df.columns), None)
print("date col", date_col)
if date_col:
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    print("date range", df[date_col].min(), df[date_col].max())

num = [c for c in ["SPEC_PROCESSED_NB", "SPEC_RECEIVED_NB", "INF_ALL", "INF_A", "INF_B", "INF_NEGATIVE", "ILI_ACTIVITY"] if c in df.columns]
if date_col and num:
    g = df.groupby(df[date_col].dt.year)[num].agg(["sum", "count"])
    print(g.to_string())
    # per-week series after collapsing sources
    wk = df.groupby(date_col)[num].sum(min_count=1)
    print("distinct weeks", len(wk))
    full = pd.date_range(wk.index.min(), wk.index.max(), freq="W-MON")
    print("expected weeks", len(full), "missing weeks", len(set(full) - set(wk.index)))
    if "INF_ALL" in wk and "SPEC_PROCESSED_NB" in wk:
        wk["pos"] = wk["INF_ALL"] / wk["SPEC_PROCESSED_NB"]
        m = wk.resample("MS").agg({"INF_ALL": "sum", "SPEC_PROCESSED_NB": "sum"})
        m["pos%"] = (100 * m["INF_ALL"] / m["SPEC_PROCESSED_NB"]).round(1)
        print(m[m.index >= "2019-01-01"].to_string())
