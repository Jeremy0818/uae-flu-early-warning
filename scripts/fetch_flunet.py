"""Download the latest WHO FluNet data for the UAE and replace data/raw/flunet/flunet_ARE.csv if it checks out.

Public API, no login. The previous file is kept as flunet_ARE.prev.csv so a refresh can be rolled back.
Prints summary counts only.
"""
import io
import os
import sys
import urllib.request
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/raw/flunet/flunet_ARE.csv"
URL = ("https://xmart-api-public.who.int/FLUMART/VIW_FNT?$format=csv"
       "&$filter=COUNTRY_CODE%20eq%20%27ARE%27")
REQUIRED = ["COUNTRY_CODE", "ISO_WEEKSTARTDATE", "ORIGIN_SOURCE", "INF_A", "INF_B", "SPEC_PROCESSED_NB"]
UA = "flu-early-warning-refresh/1.0"


def main() -> int:
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read()
    try:
        new = pd.read_csv(io.BytesIO(body), low_memory=False)
    except Exception as e:  # e.g. an HTML error page
        print("FluNet: response is not CSV:", type(e).__name__)
        return 1
    missing = [c for c in REQUIRED if c not in new.columns]
    if missing:
        print("FluNet: missing columns", missing)
        return 1
    if not (new.COUNTRY_CODE == "ARE").all() or len(new) == 0:
        print("FluNet: unexpected country rows or empty response")
        return 1
    new_max = pd.to_datetime(new.ISO_WEEKSTARTDATE).max()
    if DEST.exists():
        old = pd.read_csv(DEST, low_memory=False)
        old_max = pd.to_datetime(old.ISO_WEEKSTARTDATE).max()
        if len(new) < len(old) - 5 or new_max < old_max:
            print(f"FluNet: new download looks truncated (rows {len(old)} -> {len(new)}, "
                  f"latest week {old_max.date()} -> {new_max.date()}); keeping the existing file")
            return 1
        print(f"FluNet: rows {len(old)} -> {len(new)}, latest week {old_max.date()} -> {new_max.date()}")
        os.replace(DEST, DEST.with_suffix(".prev.csv"))
    else:
        print(f"FluNet: rows {len(new)}, latest week {new_max.date()}")
    tmp = DEST.with_suffix(".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, DEST)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
