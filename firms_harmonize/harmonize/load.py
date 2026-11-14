"""Read FIRMS CSV files (archive or NRT) into one normalized table.

Works with the files you get from the FIRMS Archive Download tool or the
FIRMS area API: MODIS Collection 6.1 and VIIRS 375 m (S-NPP, NOAA-20, NOAA-21).
The sensor is detected from the columns, and the platform from the
`satellite` field, so file names do not matter.
"""

from __future__ import annotations

import glob
import os

import pandas as pd

from .config import SENSOR_OF

_SAT_MAP = {
    # MODIS
    "terra": "Terra", "t": "Terra",
    "aqua": "Aqua", "a": "Aqua",
    # VIIRS
    "n": "SNPP", "npp": "SNPP", "snpp": "SNPP", "suomi npp": "SNPP", "suomi-npp": "SNPP",
    "1": "NOAA20", "n20": "NOAA20", "noaa-20": "NOAA20", "noaa20": "NOAA20", "j1": "NOAA20",
    "2": "NOAA21", "n21": "NOAA21", "noaa-21": "NOAA21", "noaa21": "NOAA21", "j2": "NOAA21",
}

NORMALIZED_COLUMNS = [
    "lat", "lon", "date", "time_utc", "platform", "sensor", "confidence",
    "confidence_raw", "frp", "daynight", "type", "source_file",
]


_KEEP = ["latitude", "longitude", "acq_date", "acq_time", "satellite", "confidence", "frp", "daynight", "type"]


def read_firms_csv(path: str, bbox: tuple | None = None, chunksize: int = 1_500_000) -> pd.DataFrame:
    """Read one FIRMS file (.csv, .csv.gz or a .zip holding one csv) in chunks.

    Only the needed columns are read and rows outside `bbox` are dropped chunk by
    chunk, so country-sized files of several hundred MB fit in memory.
    """
    header = [c.strip().lower() for c in pd.read_csv(path, nrows=0).columns]
    if not {"latitude", "longitude", "acq_date", "satellite", "confidence"} <= set(header):
        raise ValueError("not a FIRMS hotspot file")
    cols = [c for c in _KEEP if c in header]
    parts = []
    reader = pd.read_csv(path, usecols=lambda c: c.strip().lower() in cols, chunksize=chunksize,
                         dtype={"satellite": str, "confidence": str, "daynight": str})
    for raw in reader:
        raw.columns = [c.strip().lower() for c in raw.columns]
        if bbox is not None:
            lon0, lat0, lon1, lat1 = bbox
            raw = raw[raw.longitude.between(lon0, lon1) & raw.latitude.between(lat0, lat1)]
        if len(raw):
            parts.append(_normalize(raw, path))
    if not parts:
        return pd.DataFrame(columns=NORMALIZED_COLUMNS)
    return pd.concat(parts, ignore_index=True)


def _normalize(raw: pd.DataFrame, path: str) -> pd.DataFrame:

    # The platform decides the sensor. Column names are not reliable: some FIRMS
    # downloads label the VIIRS I4 band `bright_ti4`, others plain `brightness`.
    sat = raw["satellite"].astype(str).str.strip().str.lower().map(_SAT_MAP)
    if sat.isna().any():
        unknown = sorted(raw.loc[sat.isna(), "satellite"].astype(str).unique())[:10]
        raise ValueError(f"{os.path.basename(path)}: unknown satellite codes {unknown}")
    sensors = sat.map(SENSOR_OF).unique()
    if len(sensors) != 1:
        raise ValueError(f"{os.path.basename(path)}: mixes MODIS and VIIRS rows")
    sensor = sensors[0]

    out = pd.DataFrame({
        "lat": raw["latitude"].astype("float64"),
        "lon": raw["longitude"].astype("float64"),
        "date": pd.to_datetime(raw["acq_date"]),
        "time_utc": pd.to_numeric(raw["acq_time"], errors="coerce").astype("Int64"),
        "platform": sat,
        "sensor": sensor,
        "frp": pd.to_numeric(raw.get("frp"), errors="coerce"),
        "daynight": raw.get("daynight", pd.Series("D", index=raw.index)).astype(str).str.upper().str[0],
        "source_file": os.path.basename(path),
    })

    if "type" in raw.columns:
        out["type"] = pd.to_numeric(raw["type"], errors="coerce").astype("Int64")
    else:  # NRT files carry no type field
        out["type"] = pd.array([pd.NA] * len(raw), dtype="Int64")

    conf = raw["confidence"]
    out["confidence_raw"] = conf.astype(str)
    if sensor == "MODIS":
        out["confidence"] = pd.to_numeric(conf, errors="coerce")
    else:
        # VIIRS uses l / n / h (sometimes spelled out). Map to 0 / 50 / 100 for convenience.
        letter = conf.astype(str).str.strip().str.lower().str[0]
        out["confidence"] = letter.map({"l": 0.0, "n": 50.0, "h": 100.0})
    return out[NORMALIZED_COLUMNS]


def load_folder(folder: str, bbox: tuple | None = None) -> pd.DataFrame:
    """Load every FIRMS CSV in `folder` (recursively), clip to bbox, drop duplicates.

    Duplicates appear when archive (SP) and NRT files overlap in time; the archive
    record is kept because it carries the `type` field.
    """
    paths = sorted(
        p for ext in ("*.csv", "*.csv.gz", "*.zip")
        for p in glob.glob(os.path.join(folder, "**", ext), recursive=True)
    )
    if not paths:
        raise FileNotFoundError(f"No FIRMS CSV files found under {folder}")

    frames = []
    for p in paths:
        try:
            frames.append(read_firms_csv(p, bbox))
            print(f"  read {os.path.basename(p)}: {len(frames[-1]):,} rows in area")
        except ValueError as exc:
            print(f"  skipping {os.path.basename(p)}: {exc}")
    df = pd.concat(frames, ignore_index=True)

    if bbox is not None:
        lon0, lat0, lon1, lat1 = bbox
        df = df[(df.lon >= lon0) & (df.lon <= lon1) & (df.lat >= lat0) & (df.lat <= lat1)]

    # Prefer archive rows (type present) when the same detection appears twice
    df = df.assign(_has_type=df["type"].notna())
    df = df.sort_values("_has_type", ascending=False)
    key = pd.concat(
        [df.lat.round(4), df.lon.round(4), df.date, df.time_utc, df.platform], axis=1
    )
    df = df[~key.duplicated(keep="first")]
    df = df.drop(columns="_has_type").sort_values(["date", "time_utc"]).reset_index(drop=True)
    return df
