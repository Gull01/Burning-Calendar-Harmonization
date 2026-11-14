# Burning Calendar

**NASA Space Apps Challenge 2026: Harmonization of MODIS and VIIRS Hot Spots**

Satellites have counted fire hotspots for more than twenty years, but the record is split
between two sensor families. MODIS (Terra and Aqua) has flown since 2000. VIIRS (S-NPP,
NOAA-20, NOAA-21) took over from 2012 with sharper pixels that catch many more small fires.
Add the two together and the count jumps every time a new satellite goes up, so a fire
manager cannot tell whether a season is truly unusual or just better observed.

Burning Calendar fixes that. It rebuilds the whole record, from November 2000 to today, in one
consistent unit, and puts it in a web map where anyone can draw an area and see when it burns,
which years were worst, and how this month compares with the usual.

**Live app:** https://neon-chebakia-dba7e4.netlify.app

**Slides:** [docs/Burning_Calendar_SpaceApps2026.pdf](docs/Burning_Calendar_SpaceApps2026.pdf) (PowerPoint version in the same folder)

## What is in this repository

| Folder | What it holds |
|---|---|
| `firms_harmonize/` | The harmonization pipeline (Python): reads NASA FIRMS files, filters them, grids them, trains and validates the MODIS to VIIRS model, and builds the calendar |
| `firms_harmonize/results/` | Validation reports and charts for each region |
| `webapp/` | The web app (plain HTML, CSS and JavaScript, no server). This folder is what gets deployed |
| `docs/` | The presentation slides, as PDF and PowerPoint |

## How the harmonization works

1. **One reference sensor.** Everything is expressed as S-NPP VIIRS detections, so the number
   of satellites flying no longer changes the count.
2. **Learn the link where both sensors overlap (2012 onward).** For each grid cell and month, a
   gradient boosting model learns how what MODIS saw (counts, pixels, day and night, fire
   radiative power, activity in the surrounding area) relates to what S-NPP saw. It models
   log counts and is calibrated by calendar month, which keeps predictions realistic.
3. **Rebuild 2000 to 2011** from MODIS with that model. When S-NPP has a data gap, NOAA-20 fills
   it, scaled to S-NPP.
4. **Check it honestly.** The key test trains only on 2017 onward and predicts 2013 to 2016, the
   same backward direction used to rebuild the early years. The pipeline also compares the model
   with a simple ratio method on that test and keeps whichever is better, so a failing model
   cannot slip through.

## Results

| Region | Grid | Hotspots used | Backcast monthly r | Backcast bias |
|---|---|---|---|---|
| Pakistan | 0.1 degrees (about 11 km) | 1.5 million | 0.972 | -5.1% |
| India (Northwest) | 0.1 degrees | 3.0 million | 0.988 | -3.7% |
| Argentina | 0.25 degrees (about 28 km) | 6.3 million | 0.995 | -2.5% |

When S-NPP joined in 2012, all satellites added together jumped from one year to the next by
6.7 times over Pakistan, 7.1 times over Northwest India and 3.1 times over Argentina. The harmonized
series changed by +30%, +25% and -20%, moving the same way as Aqua MODIS on its own (+51%, +25%, -19%).
Charts for every region are in `firms_harmonize/results/<region>/break_check.png`.

What the calendar shows:

* **Pakistan:** wheat residue burning peaks in May, rice residue burning in October and November.
  October burning is now more than four times its 2002 to 2011 level, and November 2026 is running well
  above the usual level.
* **Northwest India:** detected stubble burning has fallen sharply since 2021. Part of this is
  real, but studies report farmers burning after the afternoon satellite passes, so recent years
  likely undercount fires. The app explains this and lets users compare with recent years only.
* **Argentina:** the dry season peaks in August and September, and the busiest years the tool
  finds (2020, 2003, 2008) match the major Parana Delta fire seasons.

## Run it yourself

```
cd firms_harmonize
pip install -r requirements.txt
python run_pipeline.py --input <folder with FIRMS CSV files> --region pakistan --out outputs/pakistan
python build_webapp_data.py --run outputs/pakistan --data ../webapp/data --id pakistan --name "Pakistan" --order 0
```

FIRMS files come from the FIRMS Archive Download page (https://firms.modaps.eosdis.nasa.gov/download/):
MODIS Collection 6.1 and VIIRS 375 m from S-NPP, NOAA-20 and NOAA-21, as CSV. They are large and
are not stored in this repository. To try the pipeline without downloading anything, run
`python run_pipeline.py --demo`, which uses generated test data.

To view the app locally: `cd webapp` then `python -m http.server 8000`, and open http://localhost:8000.

## Team

Gul Nawaz (team lead), Amna Akhtar, Muhammad Usman Nasir, Ramaisa Zainab and Warda Syed, Pakistan.

## Data and credits

* Active fire hotspots: NASA FIRMS, MODIS Collection 6.1 (Terra, Aqua) and VIIRS 375 m (S-NPP,
  NOAA-20, NOAA-21).
* Map tiles: Esri and its data providers; OpenStreetMap contributors.
* Libraries: Leaflet (BSD-2), Leaflet.draw (MIT), D3 (ISC), pandas, NumPy, scikit-learn, Matplotlib.

## Use of AI

AI assistance (Claude, by Anthropic) was used while building this project: to help write and debug
the Python pipeline and the web app code, to suggest validation tests, and to help draft
documentation. All data comes from NASA FIRMS; no data, images or results were generated by AI.

## License

Code is released under the MIT License (see `LICENSE`). Bundled libraries in `webapp/vendor/`
keep their own licenses.
