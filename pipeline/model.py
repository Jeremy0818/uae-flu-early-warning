"""Nowcast model: lab-anchored autoregression + seasonality, adjusted by search and environment signals.

Design principle (lesson from Google Flu Trends 2012-13): the model never predicts from searches alone.
It is anchored on the last *available* lab positivity; search and weather only explain the change
since then. All coefficients are refit each week on data that existed at that time.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# ---- settings ----
# THRESHOLD and LAB_LAG were set before back-testing. The probability cut-offs were chosen by sweeping
# them in the back-test and taking the most sensitive one whose false-alarm rate does not exceed the
# lab-only rule (see outputs/backtest_summary.json -> operating_point). With 5 scored waves, treat as provisional.
THRESHOLD = 0.15          # epidemic threshold, sentinel influenza positivity
LAB_LAG = 2               # weeks between specimen week and the result being usable
P_WARNING = 0.50          # P(positivity >= threshold) for a Warning (re-checked by backtest sweep)
P_WATCH = 0.25            # ... for a Watch
MIN_SPEC = 20             # below this a week's positivity is too noisy to use
SMALL_CELL = 30           # below this, counts/positivity are suppressed for non-surveillance roles
INCOMPLETE_FRAC = 0.5     # week with < 50% of trailing median specimens = still being reported
RIDGE_LAMBDA = 2.0
MIN_TRAIN = 26

FEATURE_GROUPS = {
    "lab": ["ar1", "mom"],
    "season": ["sin", "cos"],
    "search": ["ds_h"],
    "weather": ["dtemp", "rh"],
    "dust": ["dust"],
}
GROUP_LABELS = {
    "lab": "Recent lab positivity",
    "season": "Seasonal pattern",
    "search": "Search interest (influenza)",
    "weather": "Weather (temperature / humidity)",
    "dust": "Dust / air quality",
}
VARIANTS = {
    "full": ["lab", "season", "search"],                       # production model
    "full_env": ["lab", "season", "search", "weather", "dust"],  # ablation: environment added
    "lab_env": ["lab", "season", "weather", "dust"],
    "lab_season": ["lab", "season"],
}


def logit(p):
    p = np.clip(p, 1e-4, 1 - 1e-4)
    return np.log(p / (1 - p))


def expit(x):
    return 1 / (1 + np.exp(-x))


def norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Derive model-ready base signals from the merged weekly table (final, fully reported data)."""
    d = pd.DataFrame(index=df.index)
    spec = df.sent_spec
    trailing = spec.shift(1).rolling(8, min_periods=4).median()
    d["spec"] = spec
    d["pos"] = df.sent_pos
    d["posrate"] = df.sent_pos / spec
    d["incomplete"] = (spec < INCOMPLETE_FRAC * trailing) | (spec < MIN_SPEC)
    d["y"] = logit((df.sent_pos + 0.5) / (spec + 1))
    d.loc[d.incomplete | spec.isna(), "y"] = np.nan
    # Abu Dhabi + UAE influenza topic, averaged in log space, 3-week trailing mean (Trends is noisy for small countries)
    s_az, s_ae = np.log(df.s_az_influenza + 1), np.log(df.s_ae_influenza + 1)
    s_avg = pd.concat([s_az, s_ae], axis=1).mean(axis=1)
    d["search_raw"] = df.s_az_influenza.fillna(df.s_ae_influenza)
    d["s_week"] = s_avg
    d["s"] = s_avg.rolling(3, min_periods=2).mean()
    d["s_fever"] = np.log(df.s_az_fever.fillna(df.s_ae_fever) + 1)
    d["temp_min"] = df.temp_min
    d["rh"] = df.rh_mean
    d["dust"] = np.log(df.dust_mean + 1)
    d["dust_raw"] = df.dust_mean
    woy = d.index.isocalendar().week.astype(float).values
    d["sin"] = np.sin(2 * np.pi * woy / 52.18)
    d["cos"] = np.cos(2 * np.pi * woy / 52.18)
    return d


def design(base: pd.DataFrame, h: int, lag: int) -> pd.DataFrame:
    """Features for predicting y_t when lab is known up to t-h and other signals up to t-k (k=h-lag)."""
    k = h - lag
    X = pd.DataFrame(index=base.index)
    X["ar1"] = base.y.shift(h)
    X["mom"] = base.y.shift(h) - base.y.shift(h + 1)
    X["sin"], X["cos"] = base.sin, base.cos
    X["ds_h"] = base.s.shift(k) - base.s.shift(h)
    X["dtemp"] = base.temp_min.shift(k) - base.temp_min.shift(h)
    X["rh"] = base.rh.shift(k)
    X["dust"] = base.dust.shift(k)
    return X


@dataclass
class Fit:
    cols: list
    mu: np.ndarray
    sd: np.ndarray
    beta: np.ndarray
    sigma: float
    n: int
    fill: dict = field(default_factory=dict)

    def predict(self, x: pd.Series):
        z = self._z(x)
        return float(x["ar1"] + self.beta[0] + z @ self.beta[1:]), z

    def _z(self, x: pd.Series) -> np.ndarray:
        v = np.array([x[c] if pd.notna(x[c]) else self.fill[c] for c in self.cols], dtype=float)
        return (v - self.mu) / self.sd


def fit_ridge(X: pd.DataFrame, y: pd.Series, cols: list) -> Fit | None:
    """Ridge on the CHANGE since the last lab value (y - ar1): shrinkage pulls toward persistence, not the mean."""
    y = y - X["ar1"]
    m = y.notna() & X["ar1"].notna() & X["mom"].notna()
    # optional features: impute training mean so early weeks without dust data still train
    Xc = X.loc[m, cols].copy()
    fill = {c: float(Xc[c].mean()) if Xc[c].notna().any() else 0.0 for c in cols}
    Xc = Xc.fillna(fill)
    yc = y[m].values
    if len(yc) < MIN_TRAIN:
        return None
    mu, sd = Xc.mean().values, Xc.std().replace(0, 1).fillna(1).values
    Z = (Xc.values - mu) / sd
    A = np.column_stack([np.ones(len(Z)), Z])
    P = np.eye(A.shape[1]) * RIDGE_LAMBDA
    P[0, 0] = 0
    G = np.linalg.inv(A.T @ A + P)
    beta = G @ A.T @ yc
    hat = np.einsum("ij,jk,ik->i", A, G, A)
    loo = (yc - A @ beta) / np.clip(1 - hat, 0.05, None)  # leave-one-out residuals: honest error size
    sigma = float(np.sqrt(np.mean(loo ** 2)))
    return Fit(cols, mu, sd, beta, sigma, len(yc), fill)


def contributions(fit: Fit, z: np.ndarray, yhat: float, groups: list) -> dict:
    """Percentage-point effect of each signal group: prediction minus prediction with that group at its normal level."""
    # prediction = last lab value + intercept + sum(group terms); a group's effect = prediction minus
    # prediction with that group's term removed (i.e. group at its training-average level)
    out = {}
    for g in groups:
        idx = [fit.cols.index(c) for c in FEATURE_GROUPS[g] if c in fit.cols]
        part = float(z[idx] @ fit.beta[1:][idx])
        out[g] = round(float(100 * (expit(yhat) - expit(yhat - part))), 2)
    return out


def level_from_p(p: float) -> str:
    return "WARNING" if p >= P_WARNING else ("WATCH" if p >= P_WATCH else "NORMAL")


def vintage(base: pd.DataFrame, T: pd.Timestamp, lag: int, drop: tuple = ()) -> pd.DataFrame:
    """What the system could see at the end of week T."""
    v = base[base.index <= T].copy()
    lab_cut = T - pd.Timedelta(weeks=lag)
    v.loc[v.index > lab_cut, "y"] = np.nan
    # a lab week that was still being reported at T (low specimen count) is not usable yet
    for col in drop:
        v[col] = np.nan
    return v


def nowcast_at(base: pd.DataFrame, T: pd.Timestamp, lag: int = LAB_LAG, variant: str = "full",
               drop: tuple = (), threshold: float = THRESHOLD) -> dict | None:
    v = vintage(base, T, lag, drop)
    groups = list(VARIANTS[variant])
    mode = variant
    # degraded mode: if a signal is missing this week, fall back to a model without it
    if "search" in groups and (pd.isna(v.s.iloc[-1]) or pd.isna(v.s.shift(lag).iloc[-1])):
        groups.remove("search")
        mode = "degraded: search missing"
    if "weather" in groups and pd.isna(v.temp_min.iloc[-1]):
        groups.remove("weather")
        mode = "degraded: weather missing" if mode == variant else mode + ", weather missing"
    if "dust" in groups and pd.isna(v.dust.iloc[-1]):
        groups.remove("dust")
    cols = [c for g in groups for c in FEATURE_GROUPS[g]]
    res = {"week": T, "mode": mode, "groups": groups}
    for name, h in [("now", lag), ("next", lag + 1)]:
        X = design(v, h, lag)
        fit = fit_ridge(X, v.y, cols)
        if fit is None or pd.isna(X.iloc[-1]["ar1"]) or pd.isna(X.iloc[-1]["mom"]):
            return None
        # target week for "now" is T; for "next" it is T+1: build its feature row by shifting index
        if name == "now":
            x = X.iloc[-1]
        else:
            ext = v.reindex(v.index.append(pd.DatetimeIndex([T + pd.Timedelta(weeks=1)])))
            ext.loc[ext.index[-1], ["sin", "cos"]] = [
                math.sin(2 * math.pi * (T + pd.Timedelta(weeks=1)).isocalendar()[1] / 52.18),
                math.cos(2 * math.pi * (T + pd.Timedelta(weeks=1)).isocalendar()[1] / 52.18)]
            x = design(ext, h, lag).iloc[-1]
        yhat, z = fit.predict(x)
        p = 1 - norm_cdf((logit(threshold) - yhat) / fit.sigma)
        res[name] = {
            "rate": float(expit(yhat)),
            "lo": float(expit(yhat - 1.2816 * fit.sigma)),
            "hi": float(expit(yhat + 1.2816 * fit.sigma)),
            "p": float(p),
            "contrib": contributions(fit, z, yhat, groups),
            "coef": {c: round(float(b), 3) for c, b in zip(fit.cols, fit.beta[1:])},
            "n_train": fit.n,
        }
    res["p"] = max(res["now"]["p"], res["next"]["p"])
    res["level"] = level_from_p(res["p"])
    last_lab = v.y.last_valid_index()
    res["last_lab_week"] = last_lab
    res["last_lab_rate"] = float(expit(v.y[last_lab])) if last_lab is not None else None
    return res
