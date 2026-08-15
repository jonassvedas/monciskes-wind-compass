import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
CSV_PATH = ROOT / "raw_data.csv"
OUTPUT_PATH = ROOT / "monciskes_wind_compass.html"

MS_TO_KT = 1.9438444924406
KITE_MIN_MS = 6
ACTIVE_MONTHS = {5, 6, 7, 8, 9, 10}
ACTIVE_MONTH_ORDER = [5, 6, 7, 8, 9, 10]
EAST_SECTOR_MIN_DEG = 45
EAST_SECTOR_MAX_DEG = 135
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COMPASS_16 = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
SEASON_FOR_MONTH = {
    12: "Winter",
    1: "Winter",
    2: "Winter",
    3: "Spring",
    4: "Spring",
    5: "Spring",
    6: "Summer",
    7: "Summer",
    8: "Summer",
    9: "Autumn",
    10: "Autumn",
    11: "Autumn",
}
SEASON_ORDER = ["Winter", "Spring", "Summer", "Autumn"]
DIRECTION_BIN_SIZE = 15


def pct(count, total):
    return 100 * count / total if total else 0


def quantile(values, q):
    values = sorted(values)
    if not values:
        return 0
    pos = (len(values) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return values[lo]
    return values[lo] * (hi - pos) + values[hi] * (pos - lo)


def circular_mean(degrees):
    degrees = list(degrees)
    if not degrees:
        return None
    sin_sum = sum(math.sin(math.radians(deg)) for deg in degrees)
    cos_sum = sum(math.cos(math.radians(deg)) for deg in degrees)
    if abs(sin_sum) < 1e-12 and abs(cos_sum) < 1e-12:
        return None
    return (math.degrees(math.atan2(sin_sum, cos_sum)) + 360) % 360


def direction_label(deg):
    if deg is None:
        return ""
    return COMPASS_16[int((deg + 11.25) // 22.5) % 16]


def is_kiteable(speed):
    return speed > KITE_MIN_MS


def is_active_month(month):
    return month in ACTIVE_MONTHS


def is_east_sector(direction):
    return EAST_SECTOR_MIN_DEG <= direction <= EAST_SECTOR_MAX_DEG


def is_planning_record(row):
    return is_active_month(row["dt"].month) and not is_east_sector(row["direction"])


def load_rows():
    rows = []
    invalid = []
    with CSV_PATH.open(newline="") as file:
        reader = csv.reader(file)
        for line_number, row in enumerate(reader, 1):
            if len(row) != 4:
                invalid.append({"line": line_number, "row": row})
                continue
            try:
                observed_at = datetime.strptime(f"{row[0].strip()} {row[1].strip()}", "%Y-%m-%d %H:%M:%S")
                rows.append(
                    {
                        "dt": observed_at,
                        "speed": float(row[2]),
                        "direction": float(row[3]) % 360,
                    }
                )
            except ValueError as exc:
                invalid.append({"line": line_number, "row": row, "error": str(exc)})
    if not rows:
        raise RuntimeError(f"No readable wind observations found in {CSV_PATH}")
    return rows, invalid


def summarize(records, label_key=None, label=None):
    speeds = [row["speed"] for row in records]
    directions = [row["direction"] for row in records]
    mean_dir = circular_mean(directions)
    summary = {
        "n": len(records),
        "avg_ms": sum(speeds) / len(speeds) if speeds else 0,
        "avg_kt": (sum(speeds) / len(speeds) * MS_TO_KT) if speeds else 0,
        "median_ms": quantile(speeds, 0.5),
        "p90_ms": quantile(speeds, 0.9),
        "max_ms": max(speeds) if speeds else 0,
        "kite_pct": pct(sum(1 for speed in speeds if is_kiteable(speed)), len(speeds)),
        "strong_pct": pct(sum(1 for speed in speeds if speed >= 12), len(speeds)),
        "calm_pct": pct(sum(1 for speed in speeds if speed < 4), len(speeds)),
        "dir_deg": mean_dir,
        "dir": direction_label(mean_dir),
    }
    if label_key is not None:
        summary[label_key] = label
    return summary


def direction_profile(records, label):
    bin_count = 360 // DIRECTION_BIN_SIZE
    bins = []
    for index in range(bin_count):
        center = index * DIRECTION_BIN_SIZE
        bin_records = [
            row
            for row in records
            if int(((row["direction"] + DIRECTION_BIN_SIZE / 2) % 360) // DIRECTION_BIN_SIZE) == index
        ]
        speeds = [row["speed"] for row in bin_records]
        bins.append(
            {
                "deg": center,
                "dir": direction_label(center),
                "n": len(bin_records),
                "avg_ms": sum(speeds) / len(speeds) if speeds else 0,
                "max_ms": max(speeds) if speeds else 0,
                "kite_pct": pct(sum(1 for speed in speeds if is_kiteable(speed)), len(speeds)),
            }
        )
    return {
        "label": label,
        "n": len(records),
        "avg_ms": sum(row["speed"] for row in records) / len(records) if records else 0,
        "max_bin_ms": max((item["avg_ms"] for item in bins), default=0),
        "bins": bins,
    }


def build_data(rows, invalid):
    speeds = [row["speed"] for row in rows]
    directions = [row["direction"] for row in rows]
    planning_rows = [row for row in rows if is_planning_record(row)]
    by_date = defaultdict(list)
    for row in planning_rows:
        by_date[row["dt"].date()].append(row)

    direction_counts = Counter(direction_label(row["direction"]) for row in planning_rows)
    kite_direction_counts = Counter(direction_label(row["direction"]) for row in planning_rows if is_kiteable(row["speed"]))

    raw_monthly = []
    for month in range(1, 13):
        records = [row for row in rows if row["dt"].month == month]
        month_summary = summarize(records, "month", MONTH_NAMES[month - 1]) if records else {"month": MONTH_NAMES[month - 1], "n": 0}
        month_summary["month_number"] = month
        month_summary["active_season"] = is_active_month(month)
        raw_monthly.append(month_summary)

    monthly = []
    for month in ACTIVE_MONTH_ORDER:
        records = [row for row in planning_rows if row["dt"].month == month]
        month_summary = summarize(records, "month", MONTH_NAMES[month - 1]) if records else {"month": MONTH_NAMES[month - 1], "n": 0}
        month_summary["month_number"] = month
        month_summary["active_season"] = True
        monthly.append(month_summary)

    years = sorted({row["dt"].year for row in rows})
    monthly_by_year = {}
    for year in years:
        months = []
        for month in ACTIVE_MONTH_ORDER:
            records = [row for row in planning_rows if row["dt"].year == year and row["dt"].month == month]
            if records:
                item = summarize(records, "month", MONTH_NAMES[month - 1])
            else:
                item = {
                    "month": MONTH_NAMES[month - 1],
                    "n": 0,
                    "avg_ms": 0,
                    "avg_kt": 0,
                    "median_ms": 0,
                    "p90_ms": 0,
                    "max_ms": 0,
                    "kite_pct": 0,
                    "strong_pct": 0,
                    "calm_pct": 0,
                    "dir_deg": None,
                    "dir": "",
                }
            item["month_number"] = month
            item["active_season"] = True
            months.append(item)
        monthly_by_year[str(year)] = months

    seasonal = []
    for season in SEASON_ORDER:
        records = [row for row in planning_rows if SEASON_FOR_MONTH[row["dt"].month] == season]
        seasonal.append(summarize(records, "season", season))

    hourly = []
    for hour in range(24):
        records = [row for row in planning_rows if row["dt"].hour == hour]
        item = summarize(records, "hour", hour) if records else {"hour": hour, "n": 0}
        hourly.append(item)

    yearly = []
    for year in years:
        yearly.append(summarize([row for row in planning_rows if row["dt"].year == year], "year", year))

    direction_profiles = {
        "all": direction_profile(planning_rows, "All planning data"),
        "years": {},
        "months": {},
        "year_months": {},
    }
    for year in years:
        direction_profiles["years"][str(year)] = direction_profile(
            [row for row in planning_rows if row["dt"].year == year],
            str(year),
        )
        for month in ACTIVE_MONTH_ORDER:
            direction_profiles["year_months"][f"{year}-{month}"] = direction_profile(
                [row for row in planning_rows if row["dt"].year == year and row["dt"].month == month],
                f"{year} {MONTH_NAMES[month - 1]}",
            )
    for month in ACTIVE_MONTH_ORDER:
        direction_profiles["months"][str(month)] = direction_profile(
            [row for row in planning_rows if row["dt"].month == month],
            MONTH_NAMES[month - 1],
        )

    daily = []
    for date, records in sorted(by_date.items()):
        item = summarize(records)
        item.update(
            {
                "date": date.isoformat(),
                "max_ms": max(row["speed"] for row in records),
                "readings": len(records),
            }
        )
        daily.append(item)

    rose = []
    for direction in COMPASS_16:
        records = [row for row in planning_rows if direction_label(row["direction"]) == direction]
        total = len(planning_rows)
        rose.append(
            {
                "dir": direction,
                "n": len(records),
                "pct": pct(len(records), total),
                "calm": pct(sum(1 for row in records if row["speed"] < 4), total),
                "light": pct(sum(1 for row in records if 4 <= row["speed"] < 6), total),
                "kite": pct(sum(1 for row in records if KITE_MIN_MS < row["speed"] < 12), total),
                "strong": pct(sum(1 for row in records if row["speed"] >= 12), total),
            }
        )

    zero_heavy_months = [
        item["month"]
        for item in raw_monthly
        if item.get("n", 0) and item.get("calm_pct", 0) >= 99 and item.get("avg_ms", 0) < 0.25
    ]
    excluded_east_rows = [row for row in rows if is_active_month(row["dt"].month) and is_east_sector(row["direction"])]
    inactive_rows = [row for row in rows if not is_active_month(row["dt"].month)]

    summary = summarize(rows)
    summary.update(
        {
            "count": len(rows),
            "invalid_count": len(invalid),
            "start": min(row["dt"] for row in rows).strftime("%Y-%m-%d %H:%M"),
            "end": max(row["dt"] for row in rows).strftime("%Y-%m-%d %H:%M"),
            "days": len({row["dt"].date() for row in rows}),
            "mean_dir_deg": circular_mean(directions),
            "mean_dir": direction_label(circular_mean(directions)),
            "top_dir": Counter(direction_label(row["direction"]) for row in rows).most_common(1)[0][0],
            "top_dir_pct": pct(Counter(direction_label(row["direction"]) for row in rows).most_common(1)[0][1], len(rows)),
            "top_kite_dir": Counter(direction_label(row["direction"]) for row in rows if is_kiteable(row["speed"])).most_common(1)[0][0],
            "top_kite_dir_pct_of_kite": pct(
                Counter(direction_label(row["direction"]) for row in rows if is_kiteable(row["speed"])).most_common(1)[0][1],
                sum(Counter(direction_label(row["direction"]) for row in rows if is_kiteable(row["speed"])).values()),
            ),
            "zero_heavy_months": zero_heavy_months,
            "inactive_rows": len(inactive_rows),
            "excluded_east_rows": len(excluded_east_rows),
        }
    )

    active_summary = summarize(planning_rows)
    active_summary.update(
        {
            "count": len(planning_rows),
            "days": len({row["dt"].date() for row in planning_rows}),
            "top_dir": direction_counts.most_common(1)[0][0],
            "top_kite_dir": kite_direction_counts.most_common(1)[0][0],
            "filter_note": (
                "May-Oct only, excluding east-sector wind "
                f"({EAST_SECTOR_MIN_DEG}-{EAST_SECTOR_MAX_DEG} deg). Kiteable is >{KITE_MIN_MS} m/s."
            ),
        }
    )
    latest_planning_row = max(planning_rows, key=lambda row: row["dt"])

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "source_file": CSV_PATH.name,
        "default_compass_selection": {
            "year": latest_planning_row["dt"].year,
            "month": latest_planning_row["dt"].month,
            "month_name": MONTH_NAMES[latest_planning_row["dt"].month - 1],
        },
        "summary": summary,
        "active_summary": active_summary,
        "monthly": monthly,
        "raw_monthly": raw_monthly,
        "monthly_by_year": monthly_by_year,
        "seasonal": seasonal,
        "hourly": hourly,
        "yearly": yearly,
        "rose": rose,
        "direction_profiles": direction_profiles,
        "best_kite_days": sorted([day for day in daily if day["readings"] >= 6], key=lambda day: (day["kite_pct"], day["avg_ms"]), reverse=True)[:10],
        "windiest_days": sorted(daily, key=lambda day: day["avg_ms"], reverse=True)[:10],
    }


HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Monciskes Wind Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --ink: #18212f;
      --muted: #657085;
      --panel: #ffffff;
      --line: #d9e0e8;
      --soft: #eef3f7;
      --page: #f6f8fb;
      --blue: #2472a8;
      --teal: #0f8a7d;
      --green: #4c9a2a;
      --amber: #d88b19;
      --red: #bd4b41;
      --violet: #6656a8;
      --shadow: 0 10px 26px rgba(24, 33, 47, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--page);
    }
    header {
      padding: 24px clamp(16px, 3vw, 36px) 16px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }
    .topbar {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 20px;
      max-width: 1320px;
      margin: 0 auto;
    }
    h1 {
      margin: 0 0 8px;
      font-size: clamp(26px, 4vw, 42px);
      line-height: 1.05;
      letter-spacing: 0;
    }
    .subtitle {
      color: var(--muted);
      font-size: 15px;
      line-height: 1.45;
      max-width: 760px;
    }
    .controls {
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .segmented {
      display: inline-grid;
      grid-template-columns: 1fr 1fr;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--soft);
      min-width: 148px;
    }
    .segmented button {
      border: 0;
      padding: 9px 12px;
      background: transparent;
      color: var(--muted);
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }
    .segmented button.active {
      background: var(--ink);
      color: #fff;
    }
    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 34px;
      padding: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      white-space: nowrap;
    }
    main {
      max-width: 1320px;
      margin: 0 auto;
      padding: 20px clamp(16px, 3vw, 36px) 42px;
    }
    .kpis {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .kpi, .panel {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .kpi {
      padding: 14px 14px 12px;
      min-height: 118px;
    }
    .label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .value {
      margin-top: 8px;
      font-size: 27px;
      line-height: 1;
      font-weight: 850;
      white-space: nowrap;
    }
    .detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr);
      gap: 16px;
    }
    .panel {
      padding: 16px;
      min-width: 0;
    }
    .panel h2 {
      margin: 0 0 4px;
      font-size: 17px;
      line-height: 1.25;
      letter-spacing: 0;
    }
    .panel p {
      margin: 0 0 14px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }
    .panel-head {
      display: flex;
      align-items: flex-start;
      justify-content: center;
      gap: 16px;
      margin-bottom: 10px;
    }
    .panel-head p {
      margin-bottom: 0;
    }
    .year-tabs {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }
    .year-tabs button {
      min-width: 62px;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
      font: inherit;
      font-size: 13px;
      font-weight: 800;
      cursor: pointer;
    }
    .year-tabs button.active {
      background: var(--ink);
      border-color: var(--ink);
      color: #fff;
    }
    .select-row {
      display: grid;
      grid-template-columns: 1fr;
      gap: 14px;
      justify-items: center;
      width: 100%;
      max-width: 900px;
      margin: 0 auto;
    }
    .select-row label {
      display: inline-flex;
      align-items: center;
      gap: 7px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 800;
    }
    select {
      min-height: 36px;
      min-width: 112px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--ink);
      font: inherit;
      font-size: 13px;
      font-weight: 750;
      padding: 6px 28px 6px 10px;
    }
    .button-stack {
      display: grid;
      align-items: center;
      justify-items: center;
      width: 100%;
    }
    .button-group {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px;
      max-width: none;
    }
    .selector-button {
      min-height: 36px;
      min-width: 58px;
      padding: 7px 13px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fff;
      color: var(--muted);
      font: inherit;
      font-size: 12px;
      font-weight: 850;
      cursor: pointer;
      transition: background .15s ease, border-color .15s ease, box-shadow .15s ease, color .15s ease;
    }
    .selector-button.active {
      background: var(--selector-color, var(--ink));
      border-color: var(--selector-color, var(--ink));
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--selector-color, var(--ink)) 22%, transparent);
      color: #fff;
    }
    .selector-button:not(.active) {
      border-color: color-mix(in srgb, var(--selector-color, var(--line)) 55%, var(--line));
    }
    .year-summary {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 10px;
      margin: 4px 0 14px;
    }
    .mini-stat {
      min-height: 74px;
      padding: 10px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfd;
    }
    .mini-stat b {
      display: block;
      margin-top: 5px;
      font-size: 18px;
      line-height: 1.15;
    }
    .wide {
      grid-column: 1 / -1;
    }
    .chart {
      width: 100%;
      min-height: 250px;
    }
    .compass-chart {
      min-height: 0;
      text-align: center;
    }
    .compass-chart svg {
      width: 100%;
      max-width: 560px;
      min-width: 320px;
      margin: 0 auto;
    }
    .compass-pair {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
      align-items: start;
    }
    .compass-card {
      display: grid;
      gap: 8px;
      justify-items: center;
    }
    .plot-action {
      display: flex;
      justify-content: center;
    }
    svg {
      display: block;
      width: 100%;
      height: auto;
      overflow: visible;
    }
    .axis {
      color: var(--muted);
      font-size: 11px;
    }
    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px 16px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .legend span {
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    .swatch {
      width: 12px;
      height: 12px;
      border-radius: 3px;
      display: inline-block;
      flex: 0 0 auto;
    }
    .insights {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .insight {
      padding: 14px;
      border: 1px solid var(--line);
      background: #fff;
      border-radius: 8px;
    }
    .insight b {
      display: block;
      margin-bottom: 6px;
      font-size: 14px;
    }
    .insight span {
      display: block;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }
    .direction-list {
      display: grid;
      gap: 8px;
    }
    .dir-row {
      display: grid;
      grid-template-columns: 42px minmax(0, 1fr) 54px;
      align-items: center;
      gap: 10px;
      min-height: 28px;
      font-size: 13px;
    }
    .stack {
      display: flex;
      height: 16px;
      overflow: hidden;
      border-radius: 5px;
      background: var(--soft);
      border: 1px solid #dbe3eb;
    }
    .stack div {
      min-width: 0;
      height: 100%;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      white-space: nowrap;
    }
    th:first-child, td:first-child,
    th:nth-child(2), td:nth-child(2) {
      text-align: left;
    }
    th {
      color: var(--muted);
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: .04em;
    }
    .note {
      margin-top: 16px;
      padding: 12px 14px;
      border: 1px solid #edd5a8;
      background: #fff8eb;
      color: #6b4b15;
      border-radius: 8px;
      font-size: 13px;
      line-height: 1.45;
    }
    .footer-note {
      margin-top: 16px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.5;
    }
    @media (max-width: 1100px) {
      .kpis { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .grid { grid-template-columns: 1fr; }
      .insights { grid-template-columns: 1fr; }
    }
    @media (max-width: 700px) {
      .topbar { display: block; }
      .panel-head { display: block; }
      .year-tabs { justify-content: flex-start; margin-top: 12px; }
      .select-row { justify-content: center; margin-top: 12px; }
      .button-stack { grid-template-columns: 1fr; justify-items: center; }
      .button-group { justify-content: center; max-width: none; }
      .year-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .controls { margin-top: 14px; justify-content: flex-start; }
      .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .value { font-size: 23px; }
      .panel { padding: 13px; }
      .compass-pair { grid-template-columns: 1fr; }
      .compass-chart svg { width: 100%; min-width: 0; }
      table { font-size: 12px; }
      th, td { padding: 8px 5px; }
    }
    @media (max-width: 440px) {
      .kpis { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <div class="topbar">
      <div>
        <h1>Monciskes Wind Compass</h1>
      </div>
      <div class="controls">
        <div class="segmented" aria-label="Speed units">
          <button id="msBtn" class="active" type="button">m/s</button>
          <button id="ktBtn" type="button">kt</button>
        </div>
      </div>
    </div>
  </header>
  <main>
    <section class="grid">
      <div class="panel wide">
        <div class="panel-head">
          <div class="select-row">
            <div class="button-stack">
              <div class="button-group" id="compassYearButtons"></div>
            </div>
            <div class="button-stack">
              <div class="button-group" id="compassMonthButtons"></div>
            </div>
          </div>
        </div>
        <div class="compass-pair">
          <div class="compass-card">
            <div id="compassPlotAvg" class="chart compass-chart"></div>
            <div class="plot-action" id="compassAvgModeButton"></div>
          </div>
          <div class="compass-card">
            <div id="compassPlotMax" class="chart compass-chart"></div>
            <div class="plot-action" id="compassMaxModeButton"></div>
          </div>
        </div>
        <div class="legend" id="compassLegend">
          <span><i class="swatch" style="background: #eef3f7"></i> East-sector excluded from planning view</span>
        </div>
      </div>
    </section>
  </main>
  <script>
    /*__DATA__*/

    let unit = "ms";
    let selectedYear = String(data.yearly[data.yearly.length - 1].year);
    let selectedCompassYears = [String(data.default_compass_selection.year)];
    let selectedCompassMonths = [String(data.default_compass_selection.month)];
    let averageAvgCompassProfiles = false;
    let averageMaxCompassProfiles = false;
    const colors = {
      avg: "#2472a8",
      kite: "#4c9a2a",
      strong: "#bd4b41",
      calm: "#cfd9e3",
      light: "#d88b19",
      teal: "#0f8a7d",
      violet: "#6656a8",
      grid: "#d9e0e8",
      text: "#18212f",
      muted: "#657085"
    };
    const yearPalette = ["#2563eb", "#7c3aed", "#db2777", "#ea580c", "#16a34a", "#0891b2"];
    const monthPalette = ["#0f766e", "#65a30d", "#ca8a04", "#dc2626", "#9333ea", "#0284c7"];
    const overlayPalette = yearPalette.concat(monthPalette);

    const fmt = new Intl.NumberFormat("en", { maximumFractionDigits: 1 });
    const pctFmt = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });

    function speed(valueMs) {
      return unit === "kt" ? valueMs * 1.9438444924406 : valueMs;
    }

    function unitLabel() {
      return unit === "kt" ? "kt" : "m/s";
    }

    function speedText(valueMs) {
      return `${fmt.format(speed(valueMs))} ${unitLabel()}`;
    }

    function pctText(value) {
      return `${pctFmt.format(value)}%`;
    }

    function setUnit(nextUnit) {
      unit = nextUnit;
      document.getElementById("msBtn").classList.toggle("active", unit === "ms");
      document.getElementById("ktBtn").classList.toggle("active", unit === "kt");
      render();
    }

    function setSelectedYear(year) {
      selectedYear = String(year);
      render();
    }

    function allCompassYears() {
      return data.yearly.map(item => String(item.year));
    }

    function allCompassMonths() {
      return data.monthly.map(item => String(item.month_number));
    }

    function isAllSelected(current, allValues) {
      return current.length === allValues.length && allValues.every(value => current.includes(value));
    }

    function toggleCompassSelection(kind, value) {
      const current = kind === "year" ? selectedCompassYears : selectedCompassMonths;
      let next;
      if (current.includes(value)) {
        next = current.filter(item => item !== value);
      } else {
        next = current.concat(value);
      }
      if (!next.length) {
        next = kind === "year" ? current : [];
      }
      if (kind === "year") {
        selectedCompassYears = next;
      } else {
        selectedCompassMonths = next;
      }
      render();
    }

    function toggleCompassAverage(mode) {
      if (mode === "max") {
        averageMaxCompassProfiles = !averageMaxCompassProfiles;
      } else {
        averageAvgCompassProfiles = !averageAvgCompassProfiles;
      }
      render();
    }

    document.getElementById("msBtn").addEventListener("click", () => setUnit("ms"));
    document.getElementById("ktBtn").addEventListener("click", () => setUnit("kt"));

    function renderKpis() {
      const active = data.active_summary;
      const full = data.summary;
      const kpis = [
        ["Planning Avg Wind", speedText(active.avg_ms), `${active.n.toLocaleString()} filtered readings`],
        ["Full Avg Wind", speedText(full.avg_ms), `${full.days.toLocaleString()} measured days`],
        ["Kiteable Share", pctText(active.kite_pct), "Filtered readings over 6 m/s"],
        ["Strong Wind", pctText(active.strong_pct), "Filtered readings at 12 m/s or more"],
        ["Main Kite Direction", active.top_kite_dir, `Full dataset kiteable leader: ${full.top_kite_dir}`],
        ["Peak Reading", speedText(full.max_ms), `Data range ends ${full.end}`]
      ];
      document.getElementById("kpis").innerHTML = kpis.map(([label, value, detail]) => `
        <article class="kpi">
          <div class="label">${label}</div>
          <div class="value">${value}</div>
          <div class="detail">${detail}</div>
        </article>
      `).join("");
    }

    function renderInsights() {
      const months = data.monthly;
      const bestAvg = months.filter(m => m.active_season).slice().sort((a, b) => b.avg_ms - a.avg_ms)[0];
      const bestKite = months.filter(m => m.active_season).slice().sort((a, b) => b.kite_pct - a.kite_pct)[0];
      const strongest = months.slice().sort((a, b) => b.strong_pct - a.strong_pct)[0];
      const items = [
        ["Best average month", `${bestAvg.month} leads the planning view at ${speedText(bestAvg.avg_ms)} average wind.`],
        ["Most reliable kite month", `${bestKite.month} has ${pctText(bestKite.kite_pct)} kiteable readings, the highest monthly share.`],
        ["Storm signal", `${strongest.month} has the largest strong-wind share at ${pctText(strongest.strong_pct)}.`]
      ];
      document.getElementById("insights").innerHTML = items.map(([title, body]) => `
        <div class="insight"><b>${title}</b><span>${body}</span></div>
      `).join("");
    }

    function linePath(points) {
      return points.map((point, index) => `${index === 0 ? "M" : "L"}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(" ");
    }

    function yearColor(year) {
      const index = data.yearly.findIndex(item => String(item.year) === String(year));
      return yearPalette[(index < 0 ? 0 : index) % yearPalette.length];
    }

    function monthColor(month) {
      const index = data.monthly.findIndex(item => String(item.month_number) === String(month));
      return monthPalette[(index < 0 ? 0 : index) % monthPalette.length];
    }

    function profileWithColor(profile, color) {
      if (!profile) {
        return null;
      }
      return Object.assign({}, profile, { color });
    }

    function combineProfiles(profiles, label) {
      const usable = profiles.filter(Boolean);
      const binCount = usable[0]?.bins.length || 0;
      const bins = Array.from({ length: binCount }, (_, index) => {
        const n = usable.reduce((sum, profile) => sum + profile.bins[index].n, 0);
        const weighted = usable.reduce((sum, profile) => sum + profile.bins[index].avg_ms * profile.bins[index].n, 0);
        const maxMs = Math.max(...usable.map(profile => profile.bins[index].max_ms), 0);
        return {
          deg: usable[0].bins[index].deg,
          dir: usable[0].bins[index].dir,
          n,
          avg_ms: n ? weighted / n : 0,
          max_ms: maxMs,
          kite_pct: 0
        };
      });
      const n = usable.reduce((sum, profile) => sum + profile.n, 0);
      const avg = usable.reduce((sum, profile) => sum + profile.avg_ms * profile.n, 0);
      return {
        label,
        n,
        avg_ms: n ? avg / n : 0,
        max_bin_ms: Math.max(...bins.map(item => item.avg_ms), 0),
        max_bin_gust_ms: Math.max(...bins.map(item => item.max_ms), 0),
        bins
      };
    }

    function averageProfiles(profiles, label) {
      const usable = profiles.filter(Boolean);
      const binCount = usable[0]?.bins.length || 0;
      const bins = Array.from({ length: binCount }, (_, index) => {
        const active = usable.filter(profile => profile.bins[index].n > 0);
        const source = usable[0].bins[index];
        const avgMs = active.length
          ? active.reduce((sum, profile) => sum + profile.bins[index].avg_ms, 0) / active.length
          : 0;
        const maxMs = active.length
          ? active.reduce((sum, profile) => sum + profile.bins[index].max_ms, 0) / active.length
          : 0;
        return {
          deg: source.deg,
          dir: source.dir,
          n: active.reduce((sum, profile) => sum + profile.bins[index].n, 0),
          avg_ms: avgMs,
          max_ms: maxMs,
          kite_pct: 0
        };
      });
      const n = usable.reduce((sum, profile) => sum + profile.n, 0);
      return {
        label,
        n,
        avg_ms: usable.length ? usable.reduce((sum, profile) => sum + profile.avg_ms, 0) / usable.length : 0,
        max_bin_ms: Math.max(...bins.map(item => item.avg_ms), 0),
        max_bin_gust_ms: Math.max(...bins.map(item => item.max_ms), 0),
        bins
      };
    }

    function compactMonthLabel(months) {
      return months.map(month => data.monthly.find(item => String(item.month_number) === String(month))?.month || month).join(", ");
    }

    function compassProfiles(averageEnabled) {
      const years = selectedCompassYears;
      const months = selectedCompassMonths;
      let profiles;
      if (!years.length) {
        return [];
      }
      if (!months.length) {
        profiles = years.map(year => profileWithColor(data.direction_profiles.years[year], yearColor(year))).filter(Boolean);
      } else if (years.length === 1) {
        profiles = months
          .map(month => profileWithColor(data.direction_profiles.year_months[`${years[0]}-${month}`], monthColor(month)))
          .filter(Boolean);
      } else if (months.length === 1) {
        profiles = years
          .map(year => profileWithColor(data.direction_profiles.year_months[`${year}-${months[0]}`], yearColor(year)))
          .filter(Boolean);
      } else {
        profiles = years.map(year => combineProfiles(
          months.map(month => data.direction_profiles.year_months[`${year}-${month}`]),
          `${year} ${compactMonthLabel(months)}`
        )).map(profile => profileWithColor(profile, yearColor(profile.label.slice(0, 4))));
      }
      if (averageEnabled && profiles.length > 1) {
        return [profileWithColor(averageProfiles(profiles, "Average"), colors.teal)];
      }
      return profiles;
    }

    function compassPoint(cx, cy, radius, degrees) {
      const radians = degrees * Math.PI / 180;
      return [cx + Math.sin(radians) * radius, cy - Math.cos(radians) * radius];
    }

    function renderCompassControls() {
      const yearButtons = data.yearly.map(item => ({ label: String(item.year), value: String(item.year) }));
      const monthButtons = data.monthly.map(item => ({ label: item.month, value: String(item.month_number) }));
      document.getElementById("compassYearButtons").innerHTML = yearButtons.map(item => `
        <button type="button" style="--selector-color:${yearColor(item.value)}" class="selector-button ${selectedCompassYears.includes(item.value) ? "active" : ""}" onclick="toggleCompassSelection('year', '${item.value}')">${item.label}</button>
      `).join("");
      document.getElementById("compassMonthButtons").innerHTML = monthButtons.map(item => `
        <button type="button" style="--selector-color:${monthColor(item.value)}" class="selector-button ${selectedCompassMonths.includes(item.value) ? "active" : ""}" onclick="toggleCompassSelection('month', '${item.value}')">${item.label}</button>
      `).join("");
      document.getElementById("compassAvgModeButton").innerHTML = `
        <button type="button" style="--selector-color:${colors.teal}" class="selector-button ${averageAvgCompassProfiles ? "active" : ""}" onclick="toggleCompassAverage('avg')">Average</button>
      `;
      document.getElementById("compassMaxModeButton").innerHTML = `
        <button type="button" style="--selector-color:${colors.teal}" class="selector-button ${averageMaxCompassProfiles ? "active" : ""}" onclick="toggleCompassAverage('max')">Average</button>
      `;
    }

    function renderCompassPlot(targetId, mode) {
      const profiles = compassProfiles(mode === "max" ? averageMaxCompassProfiles : averageAvgCompassProfiles).filter(Boolean);
      const width = 560;
      const height = 480;
      const cx = width / 2;
      const cy = 238;
      const radius = 170;
      const isMax = mode === "max";
      const valueFor = item => isMax ? item.max_ms : item.avg_ms;
      const maxForProfile = profile => isMax
        ? Math.max(...profile.bins.map(item => item.max_ms), 0)
        : profile.max_bin_ms;
      const maxValue = Math.max(...profiles.map(maxForProfile), 1);
      const rings = [0.25, 0.5, 0.75, 1];
      const ringSvg = rings.map(scale => `
        <circle cx="${cx}" cy="${cy}" r="${radius * scale}" fill="none" stroke="${colors.grid}" stroke-width="1"/>
      `).join("");
      const ringLabels = rings.map(scale => {
        const label = `${fmt.format(speed(maxValue * scale))} ${unitLabel()}`;
        const y = cy - radius * scale;
        return `
          <g>
            <rect x="${cx + 8}" y="${y - 12}" width="58" height="20" rx="5" fill="rgba(255,255,255,.86)" stroke="${colors.grid}"/>
            <text x="${cx + 37}" y="${y + 3}" text-anchor="middle" fill="${colors.text}" font-size="13" font-weight="850">${label}</text>
          </g>
        `;
      }).join("");
      const degreeTicks = Array.from({ length: 24 }, (_, index) => index * 15).map(deg => {
        const outer = compassPoint(cx, cy, radius + 2, deg);
        const inner = compassPoint(cx, cy, radius - (deg % 45 === 0 ? 12 : 7), deg);
        const label = compassPoint(cx, cy, radius + 28, deg);
        const showLabel = deg % 30 === 0;
        const cardinalLabels = { 0: "N", 90: "E", 180: "S", 270: "W" };
        const labelText = cardinalLabels[deg] || String(deg) + "°";
        const isCardinal = Boolean(cardinalLabels[deg]);
        return `
          <line x1="${inner[0]}" y1="${inner[1]}" x2="${outer[0]}" y2="${outer[1]}" stroke="${colors.muted}" stroke-width="${deg % 45 === 0 ? 1.6 : 1}"/>
          ${showLabel ? `<text x="${label[0]}" y="${label[1] + (isCardinal ? 6 : 4)}" text-anchor="middle" fill="${isCardinal ? colors.text : colors.muted}" font-size="${isCardinal ? 17 : 11}" font-weight="${isCardinal ? 850 : 500}">${labelText}</text>` : ""}
        `;
      }).join("");
      const spokes = [0, 45, 90, 135, 180, 225, 270, 315].map(deg => {
        const point = compassPoint(cx, cy, radius, deg);
        return `<line x1="${cx}" y1="${cy}" x2="${point[0]}" y2="${point[1]}" stroke="${colors.grid}" stroke-width="1"/>`;
      }).join("");
      const coastTop = [cx - 8, cy - radius];
      const coastBottom = [cx - 16, cy + radius];
      const coastCurve = `M${coastTop[0]},${coastTop[1]}
        C${cx - 28},${cy - 112} ${cx + 10},${cy - 62} ${cx - 12},${cy - 8}
        C${cx - 34},${cy + 46} ${cx + 18},${cy + 102} ${coastBottom[0]},${coastBottom[1]}`;
      const seaPath = `M${cx - radius},${cy - radius}
        L${coastTop[0]},${coastTop[1]}
        C${cx - 28},${cy - 112} ${cx + 10},${cy - 62} ${cx - 12},${cy - 8}
        C${cx - 34},${cy + 46} ${cx + 18},${cy + 102} ${coastBottom[0]},${coastBottom[1]}
        L${cx - radius},${cy + radius} Z`;
      const sandPath = `M${coastTop[0]},${coastTop[1]}
        L${cx + radius},${cy - radius}
        L${cx + radius},${cy + radius}
        L${coastBottom[0]},${coastBottom[1]}
        C${cx + 18},${cy + 102} ${cx - 34},${cy + 46} ${cx - 12},${cy - 8}
        C${cx + 10},${cy - 62} ${cx - 28},${cy - 112} ${coastTop[0]},${coastTop[1]} Z`;
      const eastArcOuter = Array.from({ length: 19 }, (_, i) => compassPoint(cx, cy, radius, 45 + i * 5));
      const eastArcInner = Array.from({ length: 19 }, (_, i) => compassPoint(cx, cy, radius * .12, 135 - i * 5));
      const eastSectorPath = `M${eastArcOuter[0][0]},${eastArcOuter[0][1]} ` +
        eastArcOuter.slice(1).map(p => `L${p[0]},${p[1]}`).join(" ") + " " +
        eastArcInner.map(p => `L${p[0]},${p[1]}`).join(" ") + " Z";
      const overlays = profiles.map((profile, profileIndex) => {
        const color = profile.color || overlayPalette[profileIndex % overlayPalette.length];
        const points = profile.bins.map(item => {
          const r = (speed(valueFor(item)) / Math.max(speed(maxValue), 0.1)) * radius;
          return compassPoint(cx, cy, r, item.deg);
        });
        const area = points.length ? `${linePath(points)} Z` : "";
        const markers = profiles.length <= 3 ? profile.bins.map((item, index) => {
          const point = points[index];
          const dotRadius = item.n ? 3.2 : 2;
          return `<circle cx="${point[0]}" cy="${point[1]}" r="${dotRadius}" fill="${item.n ? color : "#b8c4cf"}"><title>${profile.label} · ${item.deg}° ${item.dir}: ${speedText(valueFor(item))} ${isMax ? "max" : "avg"}, ${item.n} readings</title></circle>`;
        }).join("") : "";
        const hoverTargets = profile.bins.map((item, index) => {
          const point = points[index];
          return `<circle cx="${point[0]}" cy="${point[1]}" r="10" fill="transparent" stroke="transparent" style="pointer-events:all"><title>${profile.label} · ${item.deg}° ${item.dir}: ${speedText(valueFor(item))} ${isMax ? "max" : "avg"}, ${item.n} readings</title></circle>`;
        }).join("");
        return `
          <path d="${area}" fill="${profileIndex === 0 ? color : "transparent"}" fill-opacity=".12" stroke="${color}" stroke-width="${profiles.length > 4 ? 2.4 : 3.5}" stroke-linejoin="round"><title>${profile.label} · ${isMax ? "maximum" : "average"} wind profile</title></path>
          ${markers}
          ${hoverTargets}
        `;
      }).join("");
      document.getElementById("compassLegend").innerHTML = profiles.map((profile, index) => `
        <span><i class="swatch" style="background:${profile.color || overlayPalette[index % overlayPalette.length]}"></i>${profile.label} · ${profile.n.toLocaleString()} readings · ${speedText(profile.avg_ms)}</span>
      `).join("") + `<span><i class="swatch" style="background: #eef3f7"></i> East-sector excluded from planning view</span>`;
      document.getElementById(targetId).innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Compass wind strength plot">
          <defs>
            <clipPath id="compassClip"><circle cx="${cx}" cy="${cy}" r="${radius}"/></clipPath>
          </defs>
          <g clip-path="url(#compassClip)">
            <path d="${seaPath}" fill="#9fcfdf"/>
            <path d="${sandPath}" fill="#e8d2a6"/>
            <path d="${coastCurve}" fill="none" stroke="#f7efd8" stroke-width="8" stroke-linecap="round"/>
            <path d="${coastCurve}" fill="none" stroke="#6aaabd" stroke-width="2" stroke-linecap="round" opacity=".7"/>
            <path d="${eastSectorPath}" fill="rgba(246, 248, 251, .42)" stroke="none"/>
          </g>
          ${ringSvg}
          ${spokes}
          ${degreeTicks}
          <circle cx="${cx}" cy="${cy}" r="${radius}" fill="none" stroke="${colors.muted}" stroke-width="1.5"/>
          ${overlays}
          ${ringLabels}
          <text x="${cx}" y="24" text-anchor="middle" fill="${colors.text}" font-size="18" font-weight="850">${isMax ? "Maximum" : "Average"}</text>
        </svg>
      `;
    }

    function renderMonthlyChart() {
      const rows = data.monthly;
      const width = 920;
      const height = 310;
      const margin = { top: 20, right: 42, bottom: 44, left: 48 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const maxSpeed = Math.max(...rows.map(d => speed(d.avg_ms)), 1);
      const maxPct = Math.max(...rows.map(d => d.kite_pct), ...rows.map(d => d.strong_pct), 1);
      const band = innerW / rows.length;
      const barW = Math.max(18, band * .46);
      const pctPoints = rows.map((d, i) => [
        margin.left + i * band + band / 2,
        margin.top + innerH - (d.kite_pct / maxPct) * innerH
      ]);
      const strongPoints = rows.map((d, i) => [
        margin.left + i * band + band / 2,
        margin.top + innerH - (d.strong_pct / maxPct) * innerH
      ]);
      const bars = rows.map((d, i) => {
        const x = margin.left + i * band + (band - barW) / 2;
        const h = (speed(d.avg_ms) / maxSpeed) * innerH;
        const fill = d.active_season ? colors.avg : "#9eb0bf";
        return `
          <rect x="${x}" y="${margin.top + innerH - h}" width="${barW}" height="${h}" rx="4" fill="${fill}">
            <title>${d.month}: ${speedText(d.avg_ms)} avg, ${pctText(d.kite_pct)} kiteable</title>
          </rect>
          <text class="axis" x="${margin.left + i * band + band / 2}" y="${height - 16}" text-anchor="middle">${d.month}</text>
        `;
      }).join("");
      const grid = [0, .25, .5, .75, 1].map(t => {
        const y = margin.top + innerH - t * innerH;
        return `<line x1="${margin.left}" x2="${width - margin.right}" y1="${y}" y2="${y}" stroke="${colors.grid}"/>`;
      }).join("");
      document.getElementById("monthlyChart").innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Monthly wind seasonality chart">
          ${grid}
          <line x1="${margin.left}" x2="${width - margin.right}" y1="${margin.top + innerH}" y2="${margin.top + innerH}" stroke="${colors.grid}"/>
          ${bars}
          <path d="${linePath(pctPoints)}" fill="none" stroke="${colors.kite}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="${linePath(strongPoints)}" fill="none" stroke="${colors.strong}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
          ${pctPoints.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${colors.kite}"><title>${rows[i].month}: ${pctText(rows[i].kite_pct)} kiteable</title></circle>`).join("")}
          ${strongPoints.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="${colors.strong}"><title>${rows[i].month}: ${pctText(rows[i].strong_pct)} strong</title></circle>`).join("")}
          <text class="axis" x="${margin.left}" y="12">Avg wind, ${unitLabel()}</text>
          <text class="axis" x="${width - margin.right}" y="12" text-anchor="end">Share of readings</text>
        </svg>
      `;
    }

    function renderSeasonChart() {
      const rows = data.seasonal;
      const width = 460;
      const height = 300;
      const margin = { top: 22, right: 20, bottom: 40, left: 52 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const maxSpeed = Math.max(...rows.map(d => speed(d.avg_ms)), 1);
      const band = innerW / rows.length;
      const barW = Math.max(42, band * .48);
      const bars = rows.map((d, i) => {
        const h = (speed(d.avg_ms) / maxSpeed) * innerH;
        const x = margin.left + i * band + (band - barW) / 2;
        const y = margin.top + innerH - h;
        return `
          <rect x="${x}" y="${y}" width="${barW}" height="${h}" rx="5" fill="${colors.teal}"></rect>
          <text class="axis" x="${x + barW / 2}" y="${y - 7}" text-anchor="middle">${fmt.format(speed(d.avg_ms))}</text>
          <text class="axis" x="${x + barW / 2}" y="${height - 16}" text-anchor="middle">${d.season}</text>
        `;
      }).join("");
      document.getElementById("seasonChart").innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Season average wind chart">
          <line x1="${margin.left}" x2="${width - margin.right}" y1="${margin.top + innerH}" y2="${margin.top + innerH}" stroke="${colors.grid}"/>
          ${bars}
          <text class="axis" x="${margin.left}" y="13">Average ${unitLabel()}</text>
        </svg>
      `;
    }

    function renderDirectionList() {
      const maxPct = Math.max(...data.rose.map(d => d.pct), 1);
      const rows = data.rose.map(item => {
        const scale = item.pct / maxPct;
        const calmW = item.pct ? (item.calm / item.pct) * 100 : 0;
        const lightW = item.pct ? (item.light / item.pct) * 100 : 0;
        const kiteW = item.pct ? (item.kite / item.pct) * 100 : 0;
        const strongW = item.pct ? (item.strong / item.pct) * 100 : 0;
        return `
          <div class="dir-row">
            <b>${item.dir}</b>
            <div class="stack" style="width:${Math.max(5, scale * 100)}%" title="${item.dir}: ${pctText(item.pct)} of all readings">
              <div style="width:${calmW}%;background:${colors.calm}"></div>
              <div style="width:${lightW}%;background:${colors.light}"></div>
              <div style="width:${kiteW}%;background:${colors.kite}"></div>
              <div style="width:${strongW}%;background:${colors.strong}"></div>
            </div>
            <span>${pctText(item.pct)}</span>
          </div>
        `;
      }).join("");
      document.getElementById("directionList").innerHTML = rows;
    }

    function renderHourlyChart() {
      const rows = data.hourly;
      const width = 820;
      const height = 300;
      const margin = { top: 20, right: 24, bottom: 38, left: 48 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const maxSpeed = Math.max(...rows.map(d => speed(d.avg_ms)), 1);
      const maxKitePct = Math.max(...rows.map(d => d.kite_pct), 1);
      const points = rows.map((d, i) => [
        margin.left + (i / (rows.length - 1)) * innerW,
        margin.top + innerH - (speed(d.avg_ms) / maxSpeed) * innerH
      ]);
      const kitePoints = rows.map((d, i) => [
        margin.left + (i / (rows.length - 1)) * innerW,
        margin.top + innerH - (d.kite_pct / maxKitePct) * innerH
      ]);
      const labels = [0, 6, 12, 18, 23].map(hour => {
        const x = margin.left + (hour / 23) * innerW;
        return `<text class="axis" x="${x}" y="${height - 14}" text-anchor="middle">${String(hour).padStart(2, "0")}:00</text>`;
      }).join("");
      document.getElementById("hourlyChart").innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Hourly wind chart">
          <line x1="${margin.left}" x2="${width - margin.right}" y1="${margin.top + innerH}" y2="${margin.top + innerH}" stroke="${colors.grid}"/>
          <path d="${linePath(points)}" fill="none" stroke="${colors.avg}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="${linePath(kitePoints)}" fill="none" stroke="${colors.kite}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" opacity=".85"/>
          ${labels}
          <text class="axis" x="${margin.left}" y="13">Average ${unitLabel()} and kiteable share</text>
        </svg>
      `;
    }

    function renderYearTabs() {
      document.getElementById("yearTabs").innerHTML = data.yearly.map(item => `
        <button type="button" class="${String(item.year) === selectedYear ? "active" : ""}" onclick="setSelectedYear(${item.year})">${item.year}</button>
      `).join("");
    }

    function renderYearMonthBreakdown() {
      const yearRows = data.monthly_by_year[selectedYear] || [];
      const baseline = data.monthly;
      const selectedSummary = data.yearly.find(item => String(item.year) === selectedYear) || { n: 0, avg_ms: 0, kite_pct: 0, strong_pct: 0, dir: "" };
      const bestMonth = yearRows.slice().sort((a, b) => b.avg_ms - a.avg_ms)[0] || { month: "", avg_ms: 0 };
      const bestKiteMonth = yearRows.slice().sort((a, b) => b.kite_pct - a.kite_pct)[0] || { month: "", kite_pct: 0 };
      document.getElementById("yearSummary").innerHTML = [
        ["Selected Year", selectedYear],
        ["Avg Wind", speedText(selectedSummary.avg_ms)],
        ["Kiteable", pctText(selectedSummary.kite_pct)],
        ["Best Month", `${bestMonth.month} · ${speedText(bestMonth.avg_ms)}`]
      ].map(([label, value]) => `
        <div class="mini-stat"><div class="label">${label}</div><b>${value}</b></div>
      `).join("");

      const width = 920;
      const height = 330;
      const margin = { top: 22, right: 46, bottom: 46, left: 50 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const maxSpeed = Math.max(...yearRows.map(d => speed(d.avg_ms)), ...baseline.map(d => speed(d.avg_ms)), 1);
      const maxPct = Math.max(...yearRows.map(d => d.kite_pct), 1);
      const band = innerW / Math.max(yearRows.length, 1);
      const barW = Math.max(24, band * .32);
      const baseW = Math.max(24, band * .22);
      const baselineBars = baseline.map((d, i) => {
        const h = (speed(d.avg_ms) / maxSpeed) * innerH;
        const x = margin.left + i * band + band / 2 - baseW - 3;
        return `<rect x="${x}" y="${margin.top + innerH - h}" width="${baseW}" height="${h}" rx="4" fill="${colors.avg}" opacity=".55"><title>All years ${d.month}: ${speedText(d.avg_ms)}</title></rect>`;
      }).join("");
      const yearBars = yearRows.map((d, i) => {
        const h = (speed(d.avg_ms) / maxSpeed) * innerH;
        const x = margin.left + i * band + band / 2 + 3;
        return `
          <rect x="${x}" y="${margin.top + innerH - h}" width="${barW}" height="${h}" rx="4" fill="${colors.violet}">
            <title>${selectedYear} ${d.month}: ${speedText(d.avg_ms)} avg, ${pctText(d.kite_pct)} kiteable</title>
          </rect>
          <text class="axis" x="${margin.left + i * band + band / 2}" y="${height - 18}" text-anchor="middle">${d.month}</text>
        `;
      }).join("");
      const kitePoints = yearRows.map((d, i) => [
        margin.left + i * band + band / 2,
        margin.top + innerH - (d.kite_pct / maxPct) * innerH
      ]);
      document.getElementById("yearMonthChart").innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Selected year monthly comparison">
          <line x1="${margin.left}" x2="${width - margin.right}" y1="${margin.top + innerH}" y2="${margin.top + innerH}" stroke="${colors.grid}"/>
          ${baselineBars}
          ${yearBars}
          <path d="${linePath(kitePoints)}" fill="none" stroke="${colors.kite}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
          ${kitePoints.map((p, i) => `<circle cx="${p[0]}" cy="${p[1]}" r="4" fill="${colors.kite}"><title>${selectedYear} ${yearRows[i].month}: ${pctText(yearRows[i].kite_pct)} kiteable</title></circle>`).join("")}
          <text class="axis" x="${margin.left}" y="13">Average ${unitLabel()}</text>
          <text class="axis" x="${width - margin.right}" y="13" text-anchor="end">Kiteable share</text>
        </svg>
      `;

      const tableRows = yearRows.map((row, index) => {
        const base = baseline[index] || { avg_ms: 0, kite_pct: 0, dir: "" };
        const diff = row.avg_ms - base.avg_ms;
        const pctDiff = row.kite_pct - base.kite_pct;
        return `
          <tr>
            <td>${row.month}</td>
            <td>${row.n.toLocaleString()}</td>
            <td>${speedText(row.avg_ms)}</td>
            <td>${diff >= 0 ? "+" : ""}${fmt.format(speed(diff))} ${unitLabel()}</td>
            <td>${pctText(row.kite_pct)}</td>
            <td>${pctDiff >= 0 ? "+" : ""}${fmt.format(pctDiff)} pts</td>
            <td>${row.dir || "-"}</td>
          </tr>
        `;
      }).join("");
      document.getElementById("yearMonthTable").innerHTML = `
        <thead><tr><th>Month</th><th>Readings</th><th>Avg</th><th>Vs baseline</th><th>Kiteable</th><th>Vs baseline</th><th>Dir</th></tr></thead>
        <tbody>${tableRows}</tbody>
      `;
    }

    function renderBestDays() {
      const rows = data.best_kite_days.map(day => `
        <tr>
          <td>${day.date}</td>
          <td>${day.dir}</td>
          <td>${speedText(day.avg_ms)}</td>
          <td>${speedText(day.max_ms)}</td>
          <td>${pctText(day.kite_pct)}</td>
          <td>${day.readings}</td>
        </tr>
      `).join("");
      document.getElementById("bestDays").innerHTML = `
        <thead><tr><th>Date</th><th>Direction</th><th>Avg</th><th>Max</th><th>Kiteable</th><th>Readings</th></tr></thead>
        <tbody>${rows}</tbody>
      `;
    }

    function renderYearChart() {
      const rows = data.yearly;
      const width = 920;
      const height = 270;
      const margin = { top: 20, right: 24, bottom: 38, left: 48 };
      const innerW = width - margin.left - margin.right;
      const innerH = height - margin.top - margin.bottom;
      const maxSpeed = Math.max(...rows.map(d => speed(d.avg_ms)), 1);
      const band = innerW / rows.length;
      const barW = Math.max(34, band * .36);
      const bars = rows.map((d, i) => {
        const h = (speed(d.avg_ms) / maxSpeed) * innerH;
        const x = margin.left + i * band + (band - barW) / 2;
        return `
          <rect x="${x}" y="${margin.top + innerH - h}" width="${barW}" height="${h}" rx="5" fill="${String(d.year) === selectedYear ? colors.strong : colors.violet}" style="cursor:pointer" onclick="setSelectedYear(${d.year})"></rect>
          <text class="axis" x="${x + barW / 2}" y="${margin.top + innerH - h - 7}" text-anchor="middle">${fmt.format(speed(d.avg_ms))}</text>
          <text class="axis" x="${x + barW / 2}" y="${height - 15}" text-anchor="middle">${d.year}</text>
        `;
      }).join("");
      document.getElementById("yearChart").innerHTML = `
        <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Yearly wind chart">
          <line x1="${margin.left}" x2="${width - margin.right}" y1="${margin.top + innerH}" y2="${margin.top + innerH}" stroke="${colors.grid}"/>
          ${bars}
          <text class="axis" x="${margin.left}" y="13">Average ${unitLabel()}</text>
        </svg>
      `;
    }

    function renderNotes() {
      const full = data.summary;
      document.getElementById("subtitle").textContent =
        `${full.count.toLocaleString()} raw wind readings from ${full.start} to ${full.end}. Planning metrics ignore Nov-Apr and east-sector wind.`;
      document.getElementById("qualityNote").textContent =
        `Data note: ${full.zero_heavy_months.join(", ")} are at least 99% calm and average below 0.25 m/s, which looks like off-season sensor inactivity or placeholder zero values. The planning view also excludes ${full.excluded_east_rows.toLocaleString()} east-sector readings from 45-135 degrees.`;
      document.getElementById("footerNote").textContent =
        `Generated ${data.generated_at} from ${data.source_file}. Kiteable is defined here as wind over 6 m/s; strong wind is 12+ m/s. Filter used for planning: ${data.active_summary.filter_note}`;
    }

    function render() {
      renderCompassControls();
      renderCompassPlot("compassPlotAvg", "avg");
      renderCompassPlot("compassPlotMax", "max");
    }

    render();
  </script>
</body>
</html>
"""


def main():
    rows, invalid = load_rows()
    data = build_data(rows, invalid)
    html = HTML_TEMPLATE.replace("/*__DATA__*/", f"const data = {json.dumps(data, ensure_ascii=False, separators=(',', ':'))};")
    OUTPUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUTPUT_PATH}")
    print(
        "Active season avg: "
        f"{data['active_summary']['avg_ms']:.2f} m/s, "
        f"kiteable {data['active_summary']['kite_pct']:.1f}%, "
        f"main kite direction {data['active_summary']['top_kite_dir']}"
    )


if __name__ == "__main__":
    main()
