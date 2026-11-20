"""Refresh Open-Meteo weather and air-quality history for Abu Dhabi (public API, no key).

These feed the weather/dust ablation and context text only; the main model does not use them,
so a failure here is reported but not fatal. Previous files are kept as *.prev.json.
"""
import json
import os
import sys
import urllib.request
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data/raw/meteo"
START = "2019-12-01"
UA = "flu-early-warning-refresh/1.0"
LOC = "latitude=24.45&longitude=54.38&timezone=Asia%2FDubai"
SOURCES = {
    "weather_auh.json": ("https://archive-api.open-meteo.com/v1/archive?{loc}&start_date={s}&end_date={e}"
                         "&daily=temperature_2m_mean,temperature_2m_min,relative_humidity_2m_mean,"
                         "dew_point_2m_mean,precipitation_sum,wind_speed_10m_max", "daily"),
    "airq_auh.json": ("https://air-quality-api.open-meteo.com/v1/air-quality?{loc}&start_date={s}&end_date={e}"
                      "&hourly=pm10,pm2_5,dust", "hourly"),
}


def main() -> int:
    end = (date.today() - timedelta(days=2)).isoformat()   # archive lags real time by a couple of days
    bad = 0
    for name, (tmpl, block) in SOURCES.items():
        dest = DIR / name
        try:
            req = urllib.request.Request(tmpl.format(loc=LOC, s=START, e=end), headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=120) as r:
                j = json.loads(r.read())
            times = j[block]["time"]
        except Exception as e:
            print(f"{name}: fetch failed ({type(e).__name__}); keeping the existing file")
            bad += 1
            continue
        if dest.exists():
            old = json.loads(dest.read_text())[block]["time"]
            if len(times) < len(old):
                print(f"{name}: shorter than existing ({len(old)} -> {len(times)}); keeping the existing file")
                bad += 1
                continue
            os.replace(dest, dest.with_suffix(".prev.json"))
        tmp = dest.with_suffix(".tmp")
        tmp.write_text(json.dumps(j))
        os.replace(tmp, dest)
        print(f"{name}: {times[0]} -> {times[-1]} ({len(times)} rows)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
