# Monciškės Wind Compass

Static dashboard for comparing average and maximum wind speed by direction at Monciškės. The published site contains only aggregated direction profiles, not the underlying observations.

## Published files

- `monciskes_wind_compass.html` is the page to host.
- `monciskes_wind_compass_data.json` is the compact data file loaded by the page. Keep it in the same directory as the HTML file.

## Updating the data

1. Obtain a fresh CSV export from the private Monciškės wind-sensor data source. Do not commit or publish that export.
2. Put it in this directory as `raw_data.csv`.
3. Run `python3 build_dashboard.py`.
4. Review the generated HTML and JSON, then commit only the generated public files and any intentional code changes.

The importer expects one observation per row with no header:

```text
YYYY-MM-DD,HH:MM:SS,wind_speed_ms,direction_degrees
2025-06-15,14:30:00,7.2,285
```

Wind speed must be in metres per second. Direction is normalized to 0-359 degrees. Invalid rows are skipped and reported when the build runs.

The compass dashboard presents May through October, and excludes the 45-135 degree east sector because the sensor does not reliably capture that direction. These filters are applied while generating the public aggregates; raw observations never appear in the published JSON.

## Local preview

The dashboard loads JSON with `fetch`, so serve the directory over HTTP rather than opening the HTML file directly:

```bash
python3 -m http.server 8000
```

Then open `http://localhost:8000/monciskes_wind_compass.html`.
