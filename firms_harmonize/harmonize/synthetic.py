"""Synthetic FIRMS files for testing the pipeline offline.

This is NOT real data. It simulates a Punjab-like region with two crop residue
burning seasons (wheat in April to May, rice in October to November), a small
summer forest fire season in the north, a rising trend, and a few persistent
industrial heat sources. Every satellite gets its own overpass time and
detection sensitivity, and VIIRS splits bigger fires into several 375 m pixels,
so the raw records show the same kind of breaks the real ones do.

Files are written in the FIRMS archive CSV schema (NOAA-21 in the NRT schema,
without the `type` column) so the real loader reads them unchanged.
"""

from __future__ import annotations

import os

import numpy as np
import pandas as pd

BBOX = (69.3, 27.7, 75.4, 34.1)

# Local solar overpass hours (day, night) and windows of operation
PLATFORMS = {
    # name: (sensor, sat code, day_hour, night_hour, start, end)
    "Terra": ("MODIS", "Terra", 10.5, 22.5, "2000-11-01", "2026-10-31"),
    "Aqua": ("MODIS", "Aqua", 13.5, 1.5, "2002-07-04", "2026-10-31"),
    "SNPP": ("VIIRS", "N", 13.5, 1.5, "2012-01-20", "2026-10-31"),
    "NOAA20": ("VIIRS", "N20", 12.7, 0.7, "2018-04-01", "2026-10-31"),
    "NOAA21": ("VIIRS", "N21", 13.0, 1.0, "2024-01-17", "2026-10-31"),
}
OUTAGES = {"SNPP": [("2022-07-26", "2022-08-31")]}  # simulated data gap


def _fields(rng, n=30000):
    lon0, lat0, lon1, lat1 = BBOX
    # crop clusters across central and southern Punjab
    k = 45
    cx = rng.uniform(70.5, 75.0, k)
    cy = rng.uniform(29.0, 32.5, k)
    w = rng.gamma(1.5, 1.0, k)
    pick = rng.choice(k, n, p=w / w.sum())
    lon = cx[pick] + rng.normal(0, 0.22, n)
    lat = cy[pick] + rng.normal(0, 0.22, n)
    crop = pd.DataFrame({"lon": lon, "lat": lat, "kind": "crop"})
    # northern forest belt
    m = 3000
    forest = pd.DataFrame({
        "lon": rng.uniform(72.8, 74.2, m), "lat": rng.uniform(33.4, 34.0, m), "kind": "forest"
    })
    f = pd.concat([crop, forest], ignore_index=True)
    f = f[(f.lon > lon0) & (f.lon < lon1) & (f.lat > lat0) & (f.lat < lat1)]
    # snap to ~250 m so repeat burns of a field share a location
    f["lon"] = (f.lon / 0.0025).round() * 0.0025
    f["lat"] = (f.lat / 0.0025).round() * 0.0025
    return f.reset_index(drop=True)


def _daily_rates(days: pd.DatetimeIndex, rng):
    doy = days.dayofyear.to_numpy()
    yrs = days.year.to_numpy()
    yfac = {y: np.exp(rng.normal(0, 0.25)) for y in np.unique(yrs)}
    yf = np.array([yfac[y] for y in yrs])
    t = yrs - 2000
    wheat = 220 * (1 + 0.015 * t) * np.exp(-0.5 * ((doy - 125) / 13) ** 2)
    rice = 380 * (1 + 0.04 * t) * np.exp(-0.5 * ((doy - 305) / 16) ** 2)
    crop = (wheat + rice) * yf + 4
    forest = (12 * np.exp(-0.5 * ((doy - 160) / 18) ** 2)) * yf + 0.2
    return crop, forest


def generate(out_dir: str, seed: int = 7, start="2000-11-01", end="2026-10-31") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    os.makedirs(out_dir, exist_ok=True)
    fields = _fields(rng)
    crop_idx = np.flatnonzero(fields.kind.eq("crop"))
    forest_idx = np.flatnonzero(fields.kind.eq("forest"))
    fw = rng.gamma(0.8, 1.0, len(fields))

    days = pd.date_range(start, end, freq="D")
    crop_rate, forest_rate = _daily_rates(days, rng)
    n_crop = rng.poisson(crop_rate)
    n_forest = rng.poisson(forest_rate)

    # one row per true fire
    day_idx = np.concatenate([np.repeat(np.arange(len(days)), n_crop),
                              np.repeat(np.arange(len(days)), n_forest)])
    kinds = np.concatenate([np.zeros(n_crop.sum(), int), np.ones(n_forest.sum(), int)])
    pc = fw[crop_idx] / fw[crop_idx].sum()
    pf = fw[forest_idx] / fw[forest_idx].sum()
    field = np.where(
        kinds == 0,
        rng.choice(crop_idx, len(kinds), p=pc),
        rng.choice(forest_idx, len(kinds), p=pf),
    )
    n = len(kinds)
    peak_frp = np.where(kinds == 0, rng.lognormal(1.4, 1.0, n), rng.lognormal(2.6, 1.1, n))
    peak_hr = np.where(kinds == 0, rng.normal(14.5, 1.5, n), rng.normal(15.0, 2.5, n))
    dur = np.where(kinds == 0, 1.0 + rng.exponential(2.0, n), 4.0 + rng.exponential(10.0, n))
    fires = pd.DataFrame({
        "day": days[day_idx], "kind": kinds, "lat": fields.lat.to_numpy()[field],
        "lon": fields.lon.to_numpy()[field], "peak_frp": peak_frp, "peak_hr": peak_hr, "dur": dur,
    })

    records = {p: [] for p in PLATFORMS}
    for p, (sensor, code, hd, hn, s0, s1) in PLATFORMS.items():
        on = (fires.day >= s0) & (fires.day <= s1)
        for a, b in OUTAGES.get(p, []):
            on &= ~((fires.day >= a) & (fires.day <= b))
        f = fires[on]
        for hour, dn in ((hd, "D"), (hn, "N")):
            ov = hour + rng.normal(0, 0.6, len(f))
            dt = (ov - f.peak_hr.to_numpy() + 12) % 24 - 12
            inst = f.peak_frp.to_numpy() * np.exp(-0.5 * (dt / (f.dur.to_numpy() / 2)) ** 2)
            if dn == "N":
                inst *= 0.6  # residual smouldering at night
            seen = rng.random(len(f)) < 0.82  # swath gaps and clouds
            if sensor == "MODIS":
                pdet = 1 - np.exp(-(inst / 9.0) ** 1.6)
            else:
                pdet = 1 - np.exp(-(inst / 2.2) ** 1.4)
            hit = seen & (rng.random(len(f)) < pdet)
            g = f[hit].assign(inst=inst[hit], dn=dn, ov=ov[hit])
            if sensor == "MODIS":
                npx = 1 + rng.poisson(g.inst / 90.0)
                spread = 0.006
            else:
                npx = 1 + rng.poisson(g.inst / 12.0)
                spread = 0.0035
            g = g.assign(npx=np.asarray(npx))
            g = g.loc[g.index.repeat(g.npx)].reset_index(drop=True)
            g["lat"] += rng.normal(0, spread, len(g))
            g["lon"] += rng.normal(0, spread, len(g))
            g["frp"] = np.round(g.inst / g.npx * rng.lognormal(0, 0.25, len(g)), 2)
            records[p].append(g)

    # persistent industrial sources (half labelled type 2 like FIRMS does, half not)
    static = pd.DataFrame({"lat": [31.52, 31.45, 30.20, 32.10, 29.40, 31.60],
                           "lon": [74.35, 74.20, 71.48, 74.18, 71.70, 73.10],
                           "type": [2, 2, 2, 0, 0, 0]})
    for p, (sensor, code, hd, hn, s0, s1) in PLATFORMS.items():
        d = days[(days >= s0) & (days <= s1)]
        rows = []
        for _, st in static.iterrows():
            keep = d[rng.random(len(d)) < (0.15 if sensor == "MODIS" else 0.55)]
            rows.append(pd.DataFrame({
                "day": keep, "lat": st.lat + rng.normal(0, 0.002, len(keep)),
                "lon": st.lon + rng.normal(0, 0.002, len(keep)), "inst": rng.uniform(4, 20, len(keep)),
                "dn": np.where(rng.random(len(keep)) < 0.5, "D", "N"), "ov": hd, "static_type": st.type,
            }))
        g = pd.concat(rows, ignore_index=True)
        g["frp"] = np.round(g.inst, 2)
        records[p].append(g)

    files = {"Terra": "fire_archive_M-C61_synthetic.csv", "Aqua": "fire_archive_M-C61_synthetic_aqua.csv",
             "SNPP": "fire_archive_SV-C2_synthetic.csv", "NOAA20": "fire_archive_J1V-C2_synthetic.csv",
             "NOAA21": "fire_nrt_J2V-C2_synthetic.csv"}
    lon_ref = 72.5
    for p, parts in records.items():
        sensor, code = PLATFORMS[p][0], PLATFORMS[p][1]
        g = pd.concat(parts, ignore_index=True)
        utc = (g.ov - lon_ref / 15.0) % 24
        hhmm = (np.floor(utc) * 100 + np.floor((utc % 1) * 60)).astype(int)
        typ = g.get("static_type", pd.Series(np.nan, index=g.index)).fillna(0).astype(int)
        if sensor == "MODIS":
            conf = np.clip(35 + 12 * np.log1p(g.inst) + rng.normal(0, 15, len(g)), 0, 100).astype(int)
            out = pd.DataFrame({
                "latitude": g.lat.round(4), "longitude": g.lon.round(4),
                "brightness": np.round(310 + 4 * np.log1p(g.inst) * 5, 1), "scan": 1.0, "track": 1.0,
                "acq_date": g.day.dt.strftime("%Y-%m-%d"), "acq_time": hhmm, "satellite": code,
                "instrument": "MODIS", "confidence": conf, "version": "6.1",
                "bright_t31": 295.0, "frp": g.frp, "daynight": g.dn, "type": typ,
            })
        else:
            u = rng.random(len(g))
            conf = np.where(u < 0.04, "l", np.where(g.inst > 25, "h", "n"))
            out = pd.DataFrame({
                "latitude": g.lat.round(5), "longitude": g.lon.round(5),
                "bright_ti4": np.round(320 + 3 * np.log1p(g.inst) * 5, 2), "scan": 0.39, "track": 0.36,
                "acq_date": g.day.dt.strftime("%Y-%m-%d"), "acq_time": hhmm, "satellite": code,
                "instrument": "VIIRS", "confidence": conf, "version": "2.0NRT" if p == "NOAA21" else 2,
                "bright_ti5": 290.0, "frp": g.frp, "daynight": g.dn, "type": typ,
            })
            if p == "NOAA21":
                out = out.drop(columns="type")
        out = out.sort_values(["acq_date", "acq_time"])
        out.to_csv(os.path.join(out_dir, files[p]), index=False)
        print(f"  {p:7s} {len(out):>9,d} detections -> {files[p]}")

    truth = fires.assign(ym=fires.day.dt.to_period("M").dt.to_timestamp()).groupby("ym").size()
    truth.rename("true_fires").to_csv(os.path.join(out_dir, "TRUTH_monthly_true_fires.txt"))
    return truth
