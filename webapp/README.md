# Burning calendar (web app)

Part 2 of our NASA Space Apps 2026 entry, "Harmonization of MODIS and VIIRS Hot Spots".
A static web app on top of the harmonized hotspot record from Part 1 (`../firms_harmonize`).

## What it does

* **Map:** hotspots per 11 km cell for any month, each cell compared with its usual for that
  month, or every individual satellite detection (MODIS and VIIRS). A month slider with play
  steps through 2000 to today.
* **Area selection:** draw a rectangle, polygon or circle on the map, or type a latitude,
  longitude and radius. Everything else updates for that area.
* **Burning calendar:** years by months, as hotspot counts or compared with the usual month.
  Hover for details; select a square to show that month on the map.
* **This month so far:** compared with the typical level by the same date (using the share of
  a month's fires that historically happen by that day), with its rank among all years.
* **Seasons, year by year, key figures** for the selected area and years.
* **Downloads:** raw hotspots in the area (CSV), the monthly calendar (CSV), calendar image (PNG).
* **How it works:** the sensor break and the validation, in plain words.

It is plain HTML, CSS and JavaScript. Leaflet, Leaflet.draw and D3 are bundled in `vendor/`,
so nothing depends on outside script servers. Map backgrounds (light gray, streets, satellite)
come from Esri and OpenStreetMap tile services that need no API key.

## Run it on your computer

Browsers block data files opened straight from disk, so use a small local server:

```
cd webapp
python -m http.server 8000
```

Then open http://localhost:8000

## Deploy to Netlify

**Easiest, no account setup beyond logging in:**
1. Go to https://app.netlify.com/drop
2. Drag the whole `webapp` folder onto the page.
3. You get a public link in under a minute. Rename it in Site settings (for example
   `punjab-burning-calendar.netlify.app`).

**From GitHub (updates automatically on every push):**
1. Put the project in a GitHub repository (for example `Gull01/punjab-burning-calendar`).
2. In Netlify: Add new site, Import an existing project, pick the repository.
3. Set the base directory to `webapp` (or wherever this folder sits). No build command.
   `netlify.toml` already tells Netlify to publish the folder as it is.

## Regions and data

The app has a region selector. Each region lives in its own folder under `data/`, and
`data/regions.json` lists them:

| Region | Folder | Grid | Model used before 2012 | Backcast check (2013 to 2016) |
|---|---|---|---|---|
| Pakistan | `data/pakistan` | 0.1 degrees (about 11 km) | gradient boosting | r 0.972, bias -5.1% |
| India (Northwest) | `data/india-northwest` | 0.1 degrees | gradient boosting | r 0.988, bias -3.7% |
| Argentina | `data/argentina` | 0.25 degrees (about 28 km) | gradient boosting | r 0.995, bias -2.5% |

Per region: `meta.json` (cells, months, data source per month, validation),
`harmonized.bin` (cells x months, value x 100 in 16-bit integers) and `det_<year>.bin`
(filtered raw detections, 15 bytes each, loaded only when needed). About 165 MB in total.

## Update or add a region

```
cd firms_harmonize
python run_pipeline.py --input <folder with that country's FIRMS files> --region pakistan --out outputs/pakistan
python build_webapp_data.py --run outputs/pakistan --data ../webapp/data --id pakistan --name "Pakistan" --order 0
```

For a big country, add `--grid 0.25 --loyo-folds 5` to `run_pipeline.py`. Keep each
country's FIRMS files in their own folder: a region box can overlap a neighbouring country.

## Credits

Hotspot data: NASA FIRMS (MODIS Collection 6.1; VIIRS 375 m from S-NPP, NOAA-20, NOAA-21).
Map tiles: Esri and its data providers; OpenStreetMap contributors. Libraries: Leaflet (BSD-2), Leaflet.draw (MIT),
D3 (ISC); licenses are in `vendor/`.
