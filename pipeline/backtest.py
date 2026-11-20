"""Real-time back-test, ablations and dashboard export.

Every week T is replayed using only what existed at the end of week T:
lab positivity up to T-LAB_LAG, search and environment up to T. Models are refit each week.
Writes:
  outputs/backtest_summary.json   metrics tables
  dashboard/data.js               everything the dashboard needs (window.EWARN = {...})
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import model as M  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BT_START = pd.Timestamp("2022-07-04")
WINDOW_BEFORE = 6        # an alert up to 6 weeks before onset counts as early warning for that wave
SEARCH_ONLY_Z = 1.5


# ---------------- ground truth ----------------
def find_waves(base: pd.DataFrame, thr: float) -> list[dict]:
    r = base.posrate.where(base.spec >= M.MIN_SPEC)
    above = (r >= thr).fillna(False).values
    weeks = base.index
    waves, i, n = [], 0, len(r)
    while i < n - 1:
        if above[i] and above[i + 1]:
            j = i
            while j < n - 1 and not (not above[j] and not above[j + 1]):
                j += 1
            end = j - 1 if j < n - 1 else n - 1
            waves.append({"onset": weeks[i], "end": weeks[end]})
            i = j + 1
        else:
            i += 1
    merged = []
    for w in waves:  # merge waves separated by < 4 weeks
        if merged and (w["onset"] - merged[-1]["end"]).days < 28:
            merged[-1]["end"] = w["end"]
        else:
            merged.append(dict(w))
    for w in merged:
        seg = r[(r.index >= w["onset"]) & (r.index <= w["end"])]
        w["peak_week"], w["peak_rate"] = seg.idxmax(), float(seg.max())
        w["ongoing"] = bool(w["end"] == weeks[-1] or (weeks[-1] - w["end"]).days < 14)
    return merged


# ---------------- runs ----------------
def run(base, variant="full", lag=M.LAB_LAG, thr=M.THRESHOLD) -> pd.DataFrame:
    rows = []
    for T in base.index[base.index >= BT_START]:
        r = M.nowcast_at(base, T, lag=lag, variant=variant, threshold=thr)
        if r is None:
            continue
        rows.append({"week": T, "level": r["level"], "p": r["p"], "p_now": r["now"]["p"], "rate_now": r["now"]["rate"],
                     "mode": r["mode"], "last_lab": r["last_lab_rate"]})
    return pd.DataFrame(rows).set_index("week")


def lab_only(base, lag=M.LAB_LAG, thr=M.THRESHOLD) -> pd.DataFrame:
    r = base.posrate.where(~base.incomplete)
    last = r.shift(lag)
    idx = base.index[base.index >= BT_START]
    return pd.DataFrame({"level": np.where(last[idx] >= thr, "WARNING", "NORMAL"),
                         "rate_now": last[idx]}, index=idx)


def calendar_rule(base, start_wk: int, length: int = 12) -> pd.DataFrame:
    idx = base.index[base.index >= BT_START]
    w = idx.isocalendar().week.values
    on = (w >= start_wk) & (w < start_wk + length)
    return pd.DataFrame({"level": np.where(on, "WARNING", "NORMAL")}, index=idx)


def search_only(base) -> pd.DataFrame:
    s = base.s
    mu = s.shift(1).rolling(52, min_periods=26).mean()
    sd = s.shift(1).rolling(52, min_periods=26).std()
    z = (s - mu) / sd
    idx = base.index[base.index >= BT_START]
    return pd.DataFrame({"level": np.where(z[idx] >= SEARCH_ONLY_Z, "WARNING", "NORMAL"), "z": z[idx]}, index=idx)


def relevel(res: pd.DataFrame, cut: float) -> pd.DataFrame:
    out = res.copy()
    out["level"] = np.where(out.p >= cut, "WARNING", "NORMAL")
    return out


# ---------------- scoring ----------------
def episodes(levels: pd.Series) -> list[tuple]:
    on = (levels == "WARNING").values
    idx, out, start = levels.index, [], None
    for k, v in enumerate(on):
        if v and start is None:
            start = idx[k]
        if (not v or k == len(on) - 1) and start is not None:
            out.append((start, idx[k] if v else idx[k - 1]))
            start = None
    return out


def score(res: pd.DataFrame, base: pd.DataFrame, waves: list, lag: int, thr: float) -> dict:
    wk = pd.Timedelta(weeks=1)
    scored = [w for w in waves if w["onset"] >= BT_START + 4 * wk]
    per_wave = []
    for w in scored:
        win = res[(res.index >= w["onset"] - WINDOW_BEFORE * wk) & (res.index <= w["end"])]
        alerts = win.index[win.level == "WARNING"]
        t_lab = w["onset"] + lag * wk
        if len(alerts):
            t_alert = alerts[0]
            lead_onset = int((w["onset"] - t_alert).days // 7)
            gain = int((t_lab - t_alert).days // 7)
        else:
            t_alert, lead_onset, gain = None, None, None
        per_wave.append({"onset": w["onset"].date().isoformat(), "peak_week": w["peak_week"].date().isoformat(),
                         "peak_rate": round(w["peak_rate"], 3),
                         "first_warning": t_alert.date().isoformat() if t_alert is not None else None,
                         "lead_vs_onset_wk": lead_onset, "gain_vs_lab_only_wk": gain,
                         "timely": bool(gain is not None and gain >= 1)})
    eps = episodes(res.level)
    def is_true(e):
        return any(e[0] <= w["end"] + wk and e[1] >= w["onset"] - WINDOW_BEFORE * wk for w in waves)
    n_true = sum(is_true(e) for e in eps)
    years = (res.index[-1] - res.index[0]).days / 365.25
    in_win = pd.Series(False, index=res.index)
    for w in waves:
        in_win |= (res.index >= w["onset"] - WINDOW_BEFORE * wk) & (res.index <= w["end"])
    off_weeks = int(((res.level == "WARNING") & ~in_win).sum())
    # weekly scores only cover weeks whose lab result is known (the newest weeks are still unreported)
    truth = base.posrate.reindex(res.index)
    known = truth.notna()
    actual = (truth >= thr) & known
    pred = (res.level == "WARNING") & known
    tp, fp = int((pred & actual).sum()), int((pred & ~actual).sum())
    fn, tn = int((~pred & actual).sum()), int((known & ~pred & ~actual).sum())
    out = {
        "waves_scored": len(scored),
        "waves_detected": sum(p["first_warning"] is not None for p in per_wave),
        "waves_timely": sum(p["timely"] for p in per_wave),
        "median_gain_vs_lab_wk": float(np.median([p["gain_vs_lab_only_wk"] for p in per_wave if p["gain_vs_lab_only_wk"] is not None])) if any(p["gain_vs_lab_only_wk"] is not None for p in per_wave) else None,
        "median_lead_vs_onset_wk": float(np.median([p["lead_vs_onset_wk"] for p in per_wave if p["lead_vs_onset_wk"] is not None])) if any(p["lead_vs_onset_wk"] is not None for p in per_wave) else None,
        "alert_episodes": len(eps), "true_episodes": n_true,
        "episode_ppv": round(n_true / len(eps), 2) if eps else None,
        "false_alarms_per_year": round((len(eps) - n_true) / years, 2),
        "offwindow_warning_weeks_per_year": round(off_weeks / years, 1),
        "warning_weeks_per_year": round(int((res.level == "WARNING").sum()) / years, 1),
        "weekly_sensitivity": round(tp / (tp + fn), 2) if tp + fn else None,
        "weekly_ppv": round(tp / (tp + fp), 2) if tp + fp else None,
        "weekly_specificity": round(tn / (tn + fp), 2) if tn + fp else None,
        "per_wave": per_wave,
    }
    if "rate_now" in res:
        truth = base.posrate.reindex(res.index).where(base.spec.reindex(res.index) >= M.MIN_SPEC)
        out["nowcast_mae_pp"] = round(100 * float((res.rate_now - truth).abs().mean()), 2)
    return out


# ---------------- explanation text ----------------
def drivers(base: pd.DataFrame, T: pd.Timestamp, r: dict, lag: int) -> list[dict]:
    b = base[base.index <= T]
    def pct(a, c):
        return None if pd.isna(a) or pd.isna(c) or c == 0 else 100 * (a / c - 1)
    s_now, s_then = b.search_raw.iloc[-1], b.search_raw.shift(lag).iloc[-1]
    f_now, f_then = np.exp(b.s_fever.iloc[-1]) - 1, np.exp(b.s_fever.shift(lag).iloc[-1]) - 1
    dtemp = b.temp_min.iloc[-1] - b.temp_min.shift(lag).iloc[-1]
    dust_now = b.dust_raw.iloc[-1]
    dust_pct = float((b.dust_raw.dropna() <= dust_now).mean() * 100) if pd.notna(dust_now) else None
    lab_w = r["last_lab_week"]
    lab_rate = r["last_lab_rate"]
    prev = base.posrate.where(~base.incomplete)[base.index < lab_w].dropna()
    lab_prev = float(prev.iloc[-1]) if len(prev) else None
    c = r["now"]["contrib"]
    items = []
    items += [
        {"group": "lab", "label": M.GROUP_LABELS["lab"], "pp": c.get("lab"),
         "text": f"Lab positivity {lab_rate*100:.1f}% in week of {lab_w:%d %b} (latest available)"
                 + (f", {'up' if lab_rate > lab_prev else 'down'} from {lab_prev*100:.1f}%" if lab_prev is not None else "")},
        {"group": "season", "label": M.GROUP_LABELS["season"], "pp": c.get("season"),
         "text": f"Week {T.isocalendar()[1]}: historically {'a rising' if c.get('season', 0) > 0 else 'a quiet/falling'} period for influenza in the UAE"},
    ]
    if "search" in c:
        sp = pct(np.exp(b.s.iloc[-1]), np.exp(b.s.shift(lag).iloc[-1]))
        fp_ = pct(f_now, f_then)
        items.append({"group": "search", "label": M.GROUP_LABELS["search"], "pp": c.get("search"),
                      "text": f"Influenza searches (Abu Dhabi + UAE, 3-wk avg) {sp:+.0f}% over {lag} wk" + (f"; fever searches {fp_:+.0f}%" if fp_ is not None else "")})
    else:
        items.append({"group": "search", "label": M.GROUP_LABELS["search"], "pp": None,
                      "text": "Search signal unavailable this week - running on lab + season (degraded mode)"})
    ctx = " (context only: tested in back-test, added no skill)"
    if pd.notna(dtemp):
        items.append({"group": "weather", "label": M.GROUP_LABELS["weather"], "pp": c.get("weather"),
                      "text": f"Night-time temperature {dtemp:+.1f} C over {lag} wk; humidity {b.rh.iloc[-1]:.0f}%"
                              + ("" if "weather" in c else ctx)})
    if pd.notna(dust_now):
        items.append({"group": "dust", "label": M.GROUP_LABELS["dust"], "pp": c.get("dust"),
                      "text": f"Dust {dust_now:.0f} ug/m3 ({dust_pct:.0f}th percentile of record)" + ("" if "dust" in c else ctx)})
    for it in items:
        it["pp"] = None if it["pp"] is None else round(float(it["pp"]), 2)
    return sorted(items, key=lambda x: -abs(x["pp"] or 0))


EMIRATES = [("AE-AZ", "Abu Dhabi"), ("AE-DU", "Dubai"), ("AE-SH", "Sharjah"), ("AE-AJ", "Ajman"),
            ("AE-RK", "Ras Al Khaimah"), ("AE-UQ", "Umm Al Quwain"), ("AE-FU", "Fujairah")]
MAX_ZERO_SHARE = 0.25   # more zero weeks than this = too little search volume to read (suppressed, like a small cell)


def zero_weeks_other() -> tuple[dict, int]:
    """Zero-week counts for the emirates in the separate [AE-AZ, AE-UQ, AE-FU] pull, read from the pull's note line."""
    head = (ROOT / "data/raw/trends/emirates_AE.txt").read_text(encoding="utf-8")
    m = re.search(r"AE-UQ (\d+), AE-FU (\d+) of (\d+)", head)
    return {"AE-UQ": int(m.group(1)), "AE-FU": int(m.group(2))}, int(m.group(3))


def emirate_block(weeks: pd.DatetimeIndex) -> dict:
    """Influenza search interest per emirate on one shared scale (one Trends comparison), aligned to ISO weeks.
    This is a search signal only: there is no lab data by emirate to confirm it."""
    t = pd.read_csv(ROOT / "data/interim/trends_emirates_AE.csv", parse_dates=["week_start"])
    t = t[t.is_partial == 0]
    t["week"] = t.week_start + pd.Timedelta(days=1)
    t = t.set_index("week").reindex(weeks)
    other, n_other = zero_weeks_other()
    out = []
    for code, name in EMIRATES:
        n = int(t[code].notna().sum()) if code in t else n_other
        zeros = int((t[code] == 0).sum()) if code in t else other[code]
        share = zeros / max(n, 1)
        suppressed = share > MAX_ZERO_SHARE
        vals = None if suppressed else [None if pd.isna(v) else int(v) for v in t[code]]
        out.append({"code": code, "name": name, "zero_share": round(share, 2), "suppressed": bool(suppressed), "values": vals})
    return {"rule": f"Emirates with zero search interest in more than {int(MAX_ZERO_SHARE*100)}% of weeks are suppressed.",
            "items": out}


def to_iso(x):
    return x.date().isoformat() if isinstance(x, pd.Timestamp) else x


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--weekly", default=str(ROOT / "data/processed/weekly.csv"))
    ap.add_argument("--stage", help="write backtest_summary.json and data.js here instead of outputs/ and dashboard/")
    args = ap.parse_args()
    df = pd.read_csv(args.weekly, parse_dates=["week"], index_col="week")
    base = M.prepare(df)
    thr, lag = M.THRESHOLD, M.LAB_LAG
    waves = find_waves(base, thr)
    print("waves:", [(w["onset"].date().isoformat(), w["end"].date().isoformat(), round(w["peak_rate"], 2)) for w in waves])

    summary = {"settings": {"threshold": thr, "lab_lag_wk": lag, "p_warning": M.P_WARNING, "p_watch": M.P_WATCH,
                            "backtest_start": BT_START.date().isoformat(), "window_before_onset_wk": WINDOW_BEFORE}}
    runs = {v: run(base, v, lag) for v in M.VARIANTS}
    lab_ref = score(lab_only(base, lag), base, waves, lag, thr)

    # operating point: most sensitive probability cut-off whose false-alarm rate <= lab-only rule
    sweep = []
    for cut in [0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7]:
        s = score(relevel(runs["full"], cut), base, waves, lag, thr)
        sweep.append({"cut": cut, **{k: s[k] for k in ["waves_timely", "median_gain_vs_lab_wk", "false_alarms_per_year",
                                                        "episode_ppv", "weekly_sensitivity", "weekly_ppv"]}})
    ok = [s for s in sweep if s["false_alarms_per_year"] <= lab_ref["false_alarms_per_year"]]
    best = max(ok, key=lambda s: (s["waves_timely"], s["median_gain_vs_lab_wk"] or -99, -s["cut"])) if ok else sweep[-1]
    cut = best["cut"]
    summary["operating_point"] = {"chosen_cut": cut, "rule": "most timely cut-off with false alarms/yr <= lab-only rule",
                                  "lab_only_false_alarms_per_year": lab_ref["false_alarms_per_year"], "sweep": sweep}
    print("sweep:"); print(pd.DataFrame(sweep).to_string(index=False)); print("chosen cut", cut)

    comp = {
        "Multi-signal nowcast (lab + season + search)": score(relevel(runs["full"], cut), base, waves, lag, thr),
        "Same + weather + dust": score(relevel(runs["full_env"], cut), base, waves, lag, thr),
        "Lab + season only (no digital signals)": score(relevel(runs["lab_season"], cut), base, waves, lag, thr),
        "Lab + season + environment (no search)": score(relevel(runs["lab_env"], cut), base, waves, lag, thr),
        "Lab-only threshold rule (current practice)": lab_ref,
        "Search-only anomaly (single signal, GFT-style)": score(search_only(base), base, waves, lag, thr),
    }
    summary["comparison"] = comp

    # fair comparison: simple rules with their own knob swept, scored against the same 15% waves
    simple = {}
    for lt in [0.08, 0.10, 0.12, 0.15]:
        simple[f"Lab-only rule, fires at {int(lt*100)}%"] = score(lab_only(base, lag, lt), base, waves, lag, thr)
    for sw in [32, 34, 36, 38]:
        simple[f"Calendar rule, ISO wk {sw}-{sw+11} every year"] = score(calendar_rule(base, sw), base, waves, lag, thr)
    for cut_ in [0.35, 0.5]:
        simple[f"Lab + season model, P>={cut_}"] = score(relevel(runs["lab_season"], cut_), base, waves, lag, thr)
        simple[f"Multi-signal model, P>={cut_}"] = score(relevel(runs["full"], cut_), base, waves, lag, thr)
    summary["simple_rules"] = simple
    fk = ["waves_timely", "median_gain_vs_lab_wk", "false_alarms_per_year", "offwindow_warning_weeks_per_year",
          "warning_weeks_per_year", "weekly_sensitivity", "weekly_ppv"]
    print("simple rules:"); print(pd.DataFrame({k: {kk: v.get(kk) for kk in fk} for k, v in simple.items()}).T.to_string())

    # reliability: predicted P(now >= thr) vs observed
    rel = runs["full"].copy()
    rel["obs"] = (base.posrate.reindex(rel.index) >= thr).astype(float)
    rel = rel[base.spec.reindex(rel.index) >= M.MIN_SPEC]
    bins = [0, 0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
    rel["bin"] = pd.cut(rel.p_now, bins, include_lowest=True)
    rt = rel.groupby("bin", observed=True).agg(n=("obs", "size"), mean_p=("p_now", "mean"), observed=("obs", "mean"))
    summary["reliability"] = [{"bin": str(b), "n": int(r.n), "mean_p": round(float(r.mean_p), 2), "observed": round(float(r.observed), 2)} for b, r in rt.iterrows()]
    summary["brier"] = round(float(((rel.p_now - rel.obs) ** 2).mean()), 3)
    print("reliability:"); print(rt.round(2).to_string()); print("brier", summary["brier"])

    # data latency sweep
    lat = {}
    for L in [1, 2, 3]:
        lat[f"lag {L} wk"] = {
            "multi_signal": score(relevel(run(base, "full", L), cut), base, waves, L, thr),
            "lab_only_rule": score(lab_only(base, L), base, waves, L, thr),
        }
    summary["latency"] = lat

    # missing inputs: search absent at random in 30% of weeks (seeded)
    rng = np.random.default_rng(7)
    b_miss = base.copy()
    mask = rng.random(len(b_miss)) < 0.30
    b_miss.loc[mask, ["s", "search_raw", "s_fever"]] = np.nan
    r_miss = relevel(run(b_miss, "full", lag), cut)
    sm = score(r_miss, base, waves, lag, thr)
    sm["degraded_weeks"] = int(r_miss["mode"].str.startswith("degraded").sum())
    summary["missing_inputs"] = {"search missing in 30% of weeks (random)": sm}

    # threshold sensitivity
    sens = {}
    for t in [0.12, 0.18]:
        wv = find_waves(base, t)
        sens[f"threshold {int(t*100)}%"] = {
            "multi_signal": score(relevel(run(base, "full", lag, t), cut), base, wv, lag, t),
            "lab_only_rule": score(lab_only(base, lag, t), base, wv, lag, t),
        }
    summary["threshold_sensitivity"] = sens

    out = Path(args.stage) / "backtest_summary.json" if args.stage else ROOT / "outputs/backtest_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2, default=to_iso))

    # ---- compact console report ----
    keys = ["waves_scored", "waves_detected", "waves_timely", "median_gain_vs_lab_wk", "median_lead_vs_onset_wk",
            "alert_episodes", "episode_ppv", "false_alarms_per_year", "weekly_sensitivity", "weekly_ppv", "nowcast_mae_pp"]
    print(pd.DataFrame({k: {kk: v.get(kk) for kk in keys} for k, v in comp.items()}).T.to_string())
    for k, v in lat.items():
        print(k, {m: {kk: s.get(kk) for kk in ["waves_timely", "median_gain_vs_lab_wk", "false_alarms_per_year", "episode_ppv"]} for m, s in v.items()})
    print("missing:", {kk: sm.get(kk) for kk in keys + ["degraded_weeks"]})
    for k, v in sens.items():
        print(k, {m: {kk: s.get(kk) for kk in ["waves_scored", "waves_timely", "median_gain_vs_lab_wk", "false_alarms_per_year"]} for m, s in v.items()})
    print("per-wave (full):")
    for p in comp["Multi-signal nowcast (lab + season + search)"]["per_wave"]:
        print("  ", p)

    # ---- dashboard export ----
    snaps = []
    for T in base.index[base.index >= BT_START]:
        r = M.nowcast_at(base, T, lag=lag)
        if r is None:
            continue
        rb = M.nowcast_at(base, T, lag=lag, variant="lab_season")
        lvl = lambda p: "WARNING" if p >= cut else ("WATCH" if p >= cut / 2 else "NORMAL")
        snaps.append({
            "week": T.date().isoformat(), "level": lvl(r["p"]), "p": round(r["p"], 3), "mode": r["mode"],
            "now": {k: round(v, 4) if isinstance(v, float) else v for k, v in r["now"].items() if k in ("rate", "lo", "hi", "p")},
            "next": {k: round(v, 4) if isinstance(v, float) else v for k, v in r["next"].items() if k in ("rate", "lo", "hi", "p")},
            "degraded": None if rb is None else {
                "level": lvl(rb["p"]), "p": round(rb["p"], 3),
                "now": {k: round(v, 4) for k, v in rb["now"].items() if k in ("rate", "lo", "hi", "p")},
                "next": {k: round(v, 4) for k, v in rb["next"].items() if k in ("rate", "lo", "hi", "p")},
                "drivers": drivers(base, T, rb, lag)},
            "last_lab_week": r["last_lab_week"].date().isoformat(),
            "drivers": drivers(base, T, r, lag),
            "coef": r["now"]["coef"], "n_train": r["now"]["n_train"],
        })
    series = []
    for w, row in base.iterrows():
        series.append({
            "week": w.date().isoformat(),
            "rate": None if pd.isna(row.posrate) else round(float(row.posrate), 4),
            "spec": None if pd.isna(row.spec) else int(row.spec),
            "pos": None if pd.isna(row.pos) else int(row.pos),
            "incomplete": bool(row.incomplete),
            "search": None if pd.isna(row.search_raw) else int(row.search_raw),
            "temp_min": None if pd.isna(row.temp_min) else round(float(row.temp_min), 1),
            "dust": None if pd.isna(row.dust_raw) else round(float(row.dust_raw), 1),
        })
    # data freshness: last week each feed actually delivered (not the model mode, which smooths over a 1-week gap)
    last = lambda s: None if s.last_valid_index() is None else s.last_valid_index().date().isoformat()
    freshness = {"as_of_week": base.index.max().date().isoformat(), "lab_last_week": last(base.spec),
                 "search_last_week": last(base.search_raw), "weather_last_week": last(base.temp_min),
                 "latest_snapshot": snaps[-1]["week"] if snaps else None}
    print("freshness:", freshness)
    payload = {
        "generated": date.today().isoformat(),
        "freshness": freshness,
        "settings": summary["settings"] | {"small_cell": M.SMALL_CELL, "min_spec": M.MIN_SPEC, "p_warning": cut, "p_watch": cut / 2},
        "waves": [{k: to_iso(v) for k, v in w.items()} for w in waves],
        "series": series, "snapshots": snaps, "backtest": summary,
        "emirates": emirate_block(base.index),
    }
    dash = Path(args.stage) / "data.js" if args.stage else ROOT / "dashboard/data.js"
    dash.parent.mkdir(parents=True, exist_ok=True)
    # version stamp: a content hash the open dashboard polls (version.json) to notice newly published data
    body = json.dumps({k: v for k, v in payload.items() if k != "generated"}, default=to_iso)  # same data = same version
    version = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    payload["version"] = version
    dash.write_text("window.EWARN = " + json.dumps(payload, default=to_iso) + ";\n", encoding="utf-8")
    (dash.parent / "version.json").write_text(json.dumps({"version": version, "generated": payload["generated"],
                                                          **freshness}) + "\n", encoding="utf-8")
    print("snapshots", len(snaps), "->", dash)


if __name__ == "__main__":
    main()
