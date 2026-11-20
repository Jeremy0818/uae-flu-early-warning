"""Merge lab, search and environment signals into one weekly table (ISO weeks, Monday start).

Inputs (all public, already aggregated):
  data/raw/flunet/flunet_ARE.csv        WHO FluNet, UAE
  data/interim/trends_*.csv             Google Trends (from scripts/trends_to_csv.py)
  data/raw/meteo/weather_auh.json       Open-Meteo archive, Abu Dhabi
  data/raw/meteo/airq_auh.json          Open-Meteo air quality (CAMS), Abu Dhabi
Output:
  data/processed/weekly.csv
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def iso_monday(s: pd.Series) -> pd.Series:
    s = pd.to_datetime(s)
    return (s - pd.to_timedelta(s.dt.day_of_week, unit="D")).dt.normalize()


def load_lab() -> pd.DataFrame:
    fn = pd.read_csv(DATA / "raw/flunet/flunet_ARE.csv", low_memory=False)
    fn["week"] = iso_monday(fn.ISO_WEEKSTARTDATE)
    fn["pos"] = fn.INF_A.fillna(0) + fn.INF_B.fillna(0)
    out = {}
    for src, key in [("SENTINEL", "sent"), ("NONSENTINEL", "nons")]:
        g = fn[fn.ORIGIN_SOURCE == src].groupby("week").agg(pos=("pos", "sum"), spec=("SPEC_PROCESSED_NB", "sum"),
                                                              inf_a=("INF_A", "sum"), inf_b=("INF_B", "sum"))
        out[key] = g.add_prefix(f"{key}_")
    lab = pd.concat(out.values(), axis=1)
    lab["all_pos"] = lab[["sent_pos", "nons_pos"]].sum(axis=1, min_count=1)
    lab["all_spec"] = lab[["sent_spec", "nons_spec"]].sum(axis=1, min_count=1)
    return lab


def load_trends() -> pd.DataFrame:
    parts = []
    for name, prefix in [("topics_AE-AZ", "s_az"), ("topics_AE", "s_ae"), ("terms_AE", "q_ae")]:
        t = pd.read_csv(DATA / f"interim/trends_{name}.csv", parse_dates=["week_start"])
        t = t[t.is_partial == 0]
        # Trends weeks run Sun-Sat; Sunday+1 = Monday of the ISO week sharing 6 of 7 days
        t["week"] = t.week_start + pd.Timedelta(days=1)
        t = t.set_index("week").drop(columns=["week_start", "is_partial"])
        rename = {}
        for c in t.columns:
            label = c.split(" ", 1)[-1] if c.startswith("/m/") else c
            rename[c] = f"{prefix}_" + label.lower().replace(" ", "_")
        parts.append(t.rename(columns=rename))
    tr = pd.concat(parts, axis=1)
    # keep only the Latin-script search terms plus topic columns (Arabic terms are near-zero volume)
    keep = [c for c in tr.columns if c.startswith(("s_az", "s_ae")) or c in ("q_ae_flu", "q_ae_fever")]
    return tr[keep]


def load_weather() -> pd.DataFrame:
    j = json.loads((DATA / "raw/meteo/weather_auh.json").read_text())
    d = pd.DataFrame(j["daily"])
    d["week"] = iso_monday(d.time)
    w = d.groupby("week").agg(
        temp_mean=("temperature_2m_mean", "mean"),
        temp_min=("temperature_2m_min", "mean"),
        rh_mean=("relative_humidity_2m_mean", "mean"),
        dewpoint=("dew_point_2m_mean", "mean"),
        precip=("precipitation_sum", "sum"),
        wind_max=("wind_speed_10m_max", "max"),
        n_days=("time", "size"),
    )
    w = w[w.n_days == 7].drop(columns="n_days")

    j = json.loads((DATA / "raw/meteo/airq_auh.json").read_text())
    a = pd.DataFrame(j["hourly"])
    a["day"] = pd.to_datetime(a.time).dt.normalize()
    daily = a.groupby("day")[["pm10", "pm2_5", "dust"]].mean()
    daily["week"] = iso_monday(daily.index.to_series())
    aq = daily.groupby("week").agg(pm10=("pm10", "mean"), pm25=("pm2_5", "mean"), dust_mean=("dust", "mean"),
                                   dust_max_day=("dust", "max"), aq_days=("pm10", "count"))
    aq.loc[aq.aq_days < 5, ["pm10", "pm25", "dust_mean", "dust_max_day"]] = float("nan")
    return w.join(aq.drop(columns="aq_days"), how="outer")


def last_complete_week(asof: pd.Timestamp) -> pd.Timestamp:
    """Monday of the last ISO week that has fully ended on or before `asof`."""
    asof = pd.Timestamp(asof).normalize()
    return asof - pd.Timedelta(days=asof.day_of_week) - pd.Timedelta(weeks=1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", help="run date YYYY-MM-DD (default today); the table ends at the last complete week")
    ap.add_argument("--out", default=str(DATA / "processed/weekly.csv"))
    a = ap.parse_args()
    lab, tr, env = load_lab(), load_trends(), load_weather()
    # The table runs to the last complete week, even when a feed is late: the newest weeks then simply
    # lack that signal and the model falls back (degraded mode) instead of the calendar standing still.
    start, end = pd.Timestamp("2021-11-15"), last_complete_week(pd.Timestamp(a.asof or date.today()))
    idx = pd.date_range(start, end, freq="W-MON", name="week")
    df = pd.DataFrame(index=idx).join(lab).join(tr).join(env)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out)
    cov = df.notna().mean().round(2)
    print("weeks", len(df), df.index.min().date(), "->", df.index.max().date())
    print("latest lab week", df.sent_spec.last_valid_index().date(),
          "| latest search week", df.s_az_influenza.last_valid_index().date())
    print("coverage:", cov.to_dict())


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
