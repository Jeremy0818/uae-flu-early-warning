"""One-command weekly refresh: fetch new data, rebuild, re-run the back-test, and stage a new dashboard.

    python scripts/refresh.py                       # fetch FluNet + weather, rebuild, stage, compare
    python scripts/refresh.py --trends PULL.json    # also install a browser Trends pull (scripts/trends_pull.js)
    python scripts/refresh.py --publish             # same, then copy the staged files into dashboard/ and outputs/
    python scripts/refresh.py --no-fetch --asof 2026-11-20   # rebuild from the files on disk for a given date

Nothing in dashboard/ or outputs/ changes unless --publish is given. Every run prints the headline
back-test numbers next to the published ones, so a refresh can never move the reported results silently.
Deploying (e.g. firebase deploy --only hosting) is a separate step.
"""
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "outputs/staging"
PY = sys.executable
FULL = "Multi-signal nowcast (lab + season + search)"
HEADLINE = ["waves_scored", "waves_timely", "false_alarms_per_year", "weekly_sensitivity", "weekly_ppv",
            "nowcast_mae_pp", "median_gain_vs_lab_wk"]


def step(label: str, args: list, fatal: bool = True) -> bool:
    print(f"\n== {label}")
    ok = subprocess.run([PY, *args], cwd=ROOT).returncode == 0
    if not ok:
        print(f"!! {label} failed" + ("" if fatal else " (continuing with the existing data)"))
        if fatal:
            sys.exit(1)
    return ok


def headline(path: Path) -> dict:
    if not path.exists():
        return {}
    s = json.loads(path.read_text())
    h = {k: s["comparison"][FULL].get(k) for k in HEADLINE}
    h["chosen_cut"] = s["operating_point"]["chosen_cut"]
    h["brier"] = s["brier"]
    return h


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--trends", help="trends_pull_YYYY-MM-DD.json saved by scripts/trends_pull.js")
    ap.add_argument("--no-fetch", action="store_true", help="skip FluNet and weather downloads")
    ap.add_argument("--asof", help="run date YYYY-MM-DD (default today)")
    ap.add_argument("--publish", action="store_true", help="copy the staged dashboard data and summary into place")
    a = ap.parse_args()

    status = {}
    if not a.no_fetch:
        status["flunet"] = step("Fetch WHO FluNet (UAE)", ["scripts/fetch_flunet.py"], fatal=False)
        status["weather"] = step("Fetch Open-Meteo weather and air quality", ["scripts/fetch_meteo.py"], fatal=False)
    if a.trends:
        status["trends"] = step("Install Google Trends pull", ["scripts/trends_import.py", a.trends], fatal=False)
    step("Parse and verify Trends files", ["scripts/trends_to_csv.py", "data"])
    build = ["pipeline/build_dataset.py", "--out", str(STAGE / "weekly.csv")] + (["--asof", a.asof] if a.asof else [])
    step("Build weekly table", build)
    step("Back-test and dashboard export (staged)", ["pipeline/backtest.py", "--weekly", str(STAGE / "weekly.csv"),
                                                      "--stage", str(STAGE)])

    new, old = headline(STAGE / "backtest_summary.json"), headline(ROOT / "outputs/backtest_summary.json")
    fresh = json.loads((STAGE / "data.js").read_text(encoding="utf-8").split("=", 1)[1].rstrip().rstrip(";"))["freshness"]
    print("\n== Result")
    print("data as of week", fresh["as_of_week"], "| lab to", fresh["lab_last_week"], "| search to",
          fresh["search_last_week"], "| weather to", fresh["weather_last_week"])
    changed = {k: (old.get(k), v) for k, v in new.items() if old.get(k) != v}
    if not changed:
        print("Back-test headline numbers unchanged.")
    else:
        print("Back-test headline numbers CHANGED (published -> new):")
        for k, (o, n) in changed.items():
            print(f"   {k}: {o} -> {n}")
        print("Update README / deck figures if you publish this.")

    if a.publish:
        shutil.copy2(STAGE / "data.js", ROOT / "dashboard/data.js")
        shutil.copy2(STAGE / "version.json", ROOT / "dashboard/version.json")   # open dashboards poll this
        shutil.copy2(STAGE / "backtest_summary.json", ROOT / "outputs/backtest_summary.json")
        shutil.copy2(STAGE / "weekly.csv", ROOT / "data/processed/weekly.csv")
        print("Published to dashboard/data.js. Deploy with: firebase deploy --only hosting")
    else:
        print(f"Staged in {STAGE.relative_to(ROOT)}. Re-run with --publish to put it live.")
    failed = [k for k, v in status.items() if not v]
    if failed:
        print("Feeds not refreshed this run:", ", ".join(failed))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
