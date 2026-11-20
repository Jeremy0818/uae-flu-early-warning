# Respiratory Early Warning · Abu Dhabi / UAE

**Future Health Digital Innovation Challenge 2026 · Population & Workforce Health Early Warning**

An explainable influenza early-warning system. Every week it estimates the *current* influenza test positivity in the UAE before the lab results are in. It combines three things: the latest available lab data, the seasonal pattern, and population search behaviour. When the estimate crosses a threshold, it issues a graded alert (NORMAL / WATCH / WARNING) with the reasons and a proportionate action for each responsible role.

> Not a medical device. Uses public, aggregated data only. Not for decisions about individuals.

**Live demo:** https://uae-flu-ewarn.web.app (public, Firebase Hosting; data refreshed weekly)

## Why it works: the honest version

Lab-confirmed surveillance (WHO FluNet) reaches decision makers about 2 weeks after specimens are taken. Search interest in influenza moves **at the same time** as infections, not before them (lag analysis: r ≈ 0.78 on levels, peaking at lag 0). Its *changes* still add real information on top of lab data (r ≈ 0.33 on 2-week changes). So the system **closes the reporting gap**; it does not predict the future from searches.

The design follows the lesson of Google Flu Trends. The model never predicts from searches alone. It is anchored on the latest lab value and predicts only the *change* since then, so ridge shrinkage pulls it toward "no change". Search only adjusts that change.

## Back-test results

The back-test replays each week from Jul 2022 to Nov 2026. Each week the model is refit using only data available that week, with a 2-week lab lag. Ground truth is waves where sentinel positivity is ≥ 15% for at least 2 weeks; 5 waves are scored.

| Approach | Waves warned before lab confirmation | False-alarm episodes / yr | Above-threshold weeks flagged | Nowcast MAE |
|---|---|---|---|---|
| **Multi-signal (lab + season + search), P ≥ 0.35** | **5 / 5** | **0** | **95%** | **3.57 pp** |
| Lab + season only, same cut-off | 5 / 5 | 0 | 95% | 4.03 pp |
| Same + weather + dust | 5 / 5 | 0.24 | 97% | 3.75 pp |
| Lab-only rule at 15% (current practice) | 0 / 5 | 0.46 | 78% | 3.87 pp (carry-forward) |
| Lab-only rule at 10% | 5 / 5 | 1.84 | 94% | – |
| Calendar rule, ISO weeks 34–45 every year | 5 / 5 | 0 | 54% | – |
| Search-only anomaly (GFT-style) | 1 / 5 | 0 | 24% | – |

Calibration is checked out of sample: when the model said 60–70%, the observed rate was 74%; when it said 70–90%, 89%. Brier score: 0.084.

**What this does and does not show**
- The UAE flu season is regular. A fixed Sep–Nov calendar rule also warned before every autumn wave with no false alarms. Most of the "weeks ahead of the lab rule" comes from seasonality, not from this model.
- What the model adds over a calendar:
  - it flags 95% of above-threshold weeks, against 54%, including off-calendar activity such as the Feb 2025 second peak;
  - it gives a current level with an 80% range;
  - it gives calibrated probabilities.
- What search adds over lab + season: +2 weeks median head start at the same cut-off, and nowcast error down from 4.03 to 3.57 pp.
- Weather and dust were tested and made results worse, so they are shown as context only.
- Only 5 scored waves, so results are reported as counts.
- The alert cut-off (P ≥ 0.35) was chosen on the same waves. The rule was: the most timely cut-off whose false alarms do not exceed the lab-only rule's.
- Trade-offs:
  - at a 1-week lab lag the model has more false alarms than the lab rule (0.47 vs 0.23 per year);
  - at a 12% threshold it has 0.72 per year;
  - the WATCH tier (P ≥ 0.175) is noisy by design: it is a "get ready" signal.
- If the search feed is missing at random in 30% of weeks, the system drops to degraded mode and still warns 5 of 5 waves early (0.24 false alarms/yr, MAE 3.91 pp).
- Historical reporting delays are simulated with a fixed lag; real FluNet vintages were not available.

Full tables are in `outputs/backtest_summary.json` and the dashboard's *Back-test evidence* tab.

## Requirement mapping

| Challenge requirement | Where |
|---|---|
| Multi-signal surveillance | Lab (FluNet sentinel), population behaviour (Google Trends, Abu Dhabi + UAE), environment (Open-Meteo weather, CAMS dust) |
| Explainable anomaly detection | Per-week contribution of each signal in percentage points, plus the plain-language driver text; time periods via a zoomable chart (1Y/2Y/All, by year, custom dates, drag to zoom); location via a by-emirate influenza search panel (Abu Dhabi, Dubai, Sharjah readable; four sparse emirates suppressed). Lab data is UAE-national only, so the emirate view is a search signal, not confirmed cases |
| Actionable decision support | Level × role playbook (surveillance officer, hospital ops, schools and community), with evidence and assumptions |
| Privacy-preserving | Aggregated inputs only; small-cell suppression (<30 specimens); role-based views (client-side in the prototype, server-side in a pilot); written no-individual / no-disciplinary use rules |
| Operational validation | Real-time back-test with lead time, sensitivity, PPV, false alarms, latency sweep, missing-input test, threshold sensitivity, single-signal comparison |
| Health & resilience impact | A calibrated, explained current-week estimate about 2 weeks before lab confirmation, including off-season activity a calendar misses. This leaves time to schedule surge staff, vaccination pushes and school advisories |

## Run it

Requires Python 3.11+ with `pandas` and `numpy` (`pip install -r requirements.txt`).

```bash
python scripts/refresh.py --no-fetch --publish      # rebuild everything from the data already in data/raw (~1-2 min)
python -m http.server 8765 --directory dashboard   # open http://localhost:8765
```

The dashboard is a static page (`dashboard/index.html` + `data.js`, no backend, no CDN). It also opens straight from disk.

## Keeping it current (weekly refresh)

The dashboard is a weekly batch product, like the surveillance bulletins it supports: each refresh adds the newest week, refits the model on everything known so far, and writes a new `data.js` plus a small `version.json`. The header shows how far each feed reaches and turns red when one is late.

**In the dashboard:** an open page checks `version.json` every 15 minutes (and whenever the tab comes back into view). When a newer refresh has been published it shows a "New data published" banner with a *Load new data* button. *Check for new data* runs the same check on demand. The page only picks up data the refresh job has published. Pulling from WHO and Google from the page itself would need a server-side endpoint with sign-in, so that nobody can trigger the pipeline anonymously; a pilot would add one (e.g. a Cloud Function restricted to the surveillance role).

| Feed | How it updates | Script |
|---|---|---|
| WHO FluNet (UAE lab) | Automatic, public API, no key | `scripts/fetch_flunet.py` |
| Open-Meteo weather / dust | Automatic, public API, no key | `scripts/fetch_meteo.py` |
| Google Trends | Semi-manual: no open API, so paste `scripts/trends_pull.js` into the browser console on trends.google.com (about 15 s), which saves one JSON file | `scripts/trends_import.py` |

```bash
python scripts/refresh.py                                   # fetch + rebuild into outputs/staging, compare with published numbers
python scripts/refresh.py --trends ~/Downloads/trends_pull_2026-11-23.json --publish   # with new search data, then put it live
firebase deploy --only hosting                              # push the new data.js
```

- **Manual runs are safe by default:** without `--publish`, nothing in `dashboard/` or `outputs/` changes, and every run prints the headline back-test numbers next to the published ones. Downloads are checked (columns, row counts, latest week, checksums) before they replace anything, and the previous files are kept as `*.prev.*` for rollback.
- **Scheduled runs publish automatically,** and each one re-runs the back-test (including the alert cut-off sweep) on the longer history, so the figures can drift. The figures in this README and the deck are as of 20 Nov 2026.
- **When a feed is late,** the table still advances to the last complete week and the header turns red. The search signal is a 3-week average, so the first missing week still runs on the remaining two weeks; from the second missing week the model switches to degraded mode (lab + season). Once lab data are more than 2 weeks old, no new nowcast is produced; the dashboard stays on the last week it could compute, and the header shows how far the data reach.
- **Each Trends pull replaces the 5-year window** and Google rescales it to 0–100, so early history drops out and old values shift slightly with each pull. The model uses week-on-week changes, which this affects little.
- **Automation:** `.github/workflows/weekly-refresh.yml` runs FluNet + weather + rebuild + Firebase deploy every Tuesday once the repo is on GitHub (setup notes in the file; not yet run). Trends stays a weekly manual pull; [Google's official Trends API](https://developers.google.com/search/apis/trends) (alpha, access by application) would remove that step.
- **Limitation:** the prototype is not real-time. Data are as of the week shown in the header (currently the week of 9 Nov 2026, lab to 2 Nov). A pilot on DoH's own sentinel feed would refresh the same way, with a shorter lab delay.

## Demo script (2–3 min)

1. **Latest week** (Nov 2026): WARNING, 20.7% estimated, with the signal breakdown. Switch roles to show how the views change (counts, probabilities and coefficients are hidden outside the surveillance role).
2. **Replay 2023**: drag to 18 Sep 2023 and tick *Show what happened next*. The system says WARNING; the lab-only rule fires 5 weeks later. Search interest (+4 pp) is what tips it from WATCH to WARNING.
3. **Simulate search-feed outage** on that week: degraded mode, back to WATCH, with a banner. The system fails safe.
4. **Back-test tab**: 5 of 5 waves, 0 false alarms, 95% of above-threshold weeks flagged, the calibration table, and the fair test against a calendar rule.
5. **Governance tab**: data sources, privacy controls, role matrix, model card.

## Layout

```
data/raw/        downloads: FluNet, Open-Meteo, Trends (compact text + checksums)
data/interim/    Trends CSVs
data/processed/  weekly merged table
pipeline/        build_dataset.py, model.py (nowcast + alerting + explanations), backtest.py
scripts/         refresh.py (weekly update), fetch_*.py, trends_pull.js + trends_import.py, checks
.github/         weekly-refresh.yml (scheduled refresh + Firebase deploy)
outputs/         backtest_summary.json (staging/ holds unpublished refresh output)
dashboard/       index.html, data.js
```

## Path to pilot

- **Who:** the DoH Abu Dhabi surveillance team.
- **Inputs:** swap FluNet for DoH's own weekly sentinel feed. That shortens the lag and gives emirate-level ground truth.
- **More signals:** add aggregated ED respiratory visits, pharmacy sales and school absenteeism (aggregated per site, above small-cell thresholds). The same model structure takes each new signal as one more feature group.
- **Wider rollout:** the same code works for any FluNet country plus Trends region: GCC, Malaysia.
