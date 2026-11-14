"""MODIS to VIIRS-equivalent transfer models and the fused harmonized series.

Harmonized unit: hotspot detections that S-NPP VIIRS would report (after the
same filtering) for a cell and month. VIIRS is the reference because it is the
future of the record and the more detailed sensor; MODIS supplies the history.

Why S-NPP alone: pooling every satellite makes counts jump each time a platform
is added (2012, 2018, 2024). Fixing one reference platform removes that.
Aqua MODIS is the main predictor because it shares the early afternoon
overpass with S-NPP; Terra (morning) adds information and covers 2000 to 2002.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

from .config import Settings

MOD_VARS = ["n_det", "n_px", "n_px_day", "n_px_night", "frp_sum", "n_days"]


BLOCKS = (0.5, 2.0)  # neighbourhood scales in degrees


def add_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Features describe what MODIS saw in the same month only.

    Long-term climatology features were tried and dropped: they pull predictions
    toward the average, which overestimates quiet years and underestimates busy
    ones when the model is applied outside the overlap period. Same-month
    neighbourhood activity carries the "how active is the area right now" signal
    instead, which also lets the model predict VIIRS small-fire detections in
    cells where MODIS saw nothing.
    """
    out = panel.copy()
    out["moy_sin"] = np.sin(2 * np.pi * out.month / 12)
    out["moy_cos"] = np.cos(2 * np.pi * out.month / 12)
    for p in ("Aqua", "Terra"):
        n = out[f"{p}_n_det"]
        out[f"{p}_frp_mean"] = np.where(n > 0, out[f"{p}_frp_sum"] / n.replace(0, np.nan), 0.0)
        for b in BLOCKS:
            key = [np.floor(out.cell_lat / b), np.floor(out.cell_lon / b), out.ym]
            for v in ("n_det", "frp_sum"):
                agg = out.groupby(key)[f"{p}_{v}"].transform("sum")
                out[f"{p}_{v}_b{b}"] = agg.where(out[f"{p}_{v}"].notna())
    return out


def _mod_features(p: str) -> list[str]:
    return (
        [f"{p}_{v}" for v in MOD_VARS] + [f"{p}_frp_mean"]
        + [f"{p}_{v}_b{b}" for b in BLOCKS for v in ("n_det", "frp_sum")]
    )


FEATURES = {
    "aqua": _mod_features("Aqua") + _mod_features("Terra") + ["moy_sin", "moy_cos"],
    "terra": _mod_features("Terra") + ["moy_sin", "moy_cos"],
}


def training_rows(feat: pd.DataFrame, s: Settings, kind: str) -> pd.Series:
    ref = f"{s.reference_platform}_n_det"
    need = feat[ref].notna() & (feat.ym >= pd.Timestamp(s.overlap_start))
    need &= feat["Terra_n_det"].notna()
    if kind == "aqua":
        need &= feat["Aqua_n_det"].notna()
    return need


class RatioBaseline:
    """Simple, explainable baseline: shrunken cell ratio when MODIS sees fire,
    and a shrunken cell by calendar month mean when MODIS sees nothing."""

    def __init__(self, s: Settings, modis: str = "Aqua"):
        self.s, self.modis = s, modis

    def fit(self, df: pd.DataFrame, y: pd.Series):
        k = self.s.shrinkage_k
        m = df[f"{self.modis}_n_det"]
        pos = m > 0
        R = y[pos].sum() / max(m[pos].sum(), 1)
        g = pd.DataFrame({"cell": df.cell, "y": y, "m": m})[pos].groupby("cell").sum()
        self.ratio = (g.y + k * R) / (g.m + k)
        self.R = R
        z = pd.DataFrame({"cell": df.cell, "month": df.month, "y": y})[~pos]
        Z = z.groupby("month").y.mean()
        gz = z.groupby(["cell", "month"]).y.agg(["sum", "count"])
        prior = Z.reindex(gz.index.get_level_values("month")).to_numpy()
        self.zero = (gz["sum"] + 5 * prior) / (gz["count"] + 5)
        self.Z = Z
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        m = df[f"{self.modis}_n_det"].to_numpy()
        r = df.cell.map(self.ratio).fillna(self.R).to_numpy()
        idx = pd.MultiIndex.from_arrays([df.cell, df.month])
        z = pd.Series(self.zero).reindex(idx).to_numpy()
        z = np.where(np.isnan(z), df.month.map(self.Z).fillna(0).to_numpy(), z)
        return np.where(m > 0, r * m, z)


class GBMTransfer:
    """Gradient boosting on log(1 + count), calibrated per calendar month.

    Modelling log counts keeps every prediction inside the range seen in training.
    A Poisson-loss version was tried first: it extrapolates exponentially and, on
    Argentina, produced cells with hundreds of millions of hotspots.
    """

    def __init__(self, s: Settings, kind: str):
        self.s, self.kind = s, kind
        self.cols = list(FEATURES[kind])
        if s.use_location:
            self.cols += ["cell_lat", "cell_lon"]
        self.cols += list(s.extra_features)
        self.model = HistGradientBoostingRegressor(
            loss="squared_error",
            max_iter=s.gbm_max_iter,
            learning_rate=s.gbm_learning_rate,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=s.random_state,
        )
        self.k_month = None
        self.k_all = 1.0

    def _raw(self, df: pd.DataFrame) -> np.ndarray:
        return np.clip(np.expm1(self.model.predict(df[self.cols])), 0, None)

    def fit(self, df: pd.DataFrame, y: pd.Series):
        y = np.asarray(y, dtype="float64")
        self.model.fit(df[self.cols], np.log1p(y))
        # Back-transforming log predictions underestimates totals, more in busy
        # months. Calibrate per calendar month so training totals match observed
        # totals (tested against Duan smearing: bias -1.8% vs -11.2% on Pakistan).
        p = self._raw(df)
        t = pd.DataFrame({"y": y, "p": p, "m": df.month.to_numpy()}).groupby("m").sum()
        self.k_all = float(t.y.sum() / max(t.p.sum(), 1e-9))
        self.k_month = (t.y / t.p.where(t.p > 0)).fillna(self.k_all).clip(0.2, 5).to_dict()
        return self

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        k = df.month.map(self.k_month).fillna(self.k_all).to_numpy()
        return self._raw(df) * k


class TerraRatio(RatioBaseline):
    def __init__(self, s: Settings):
        super().__init__(s, modis="Terra")


def viirs_cross_ratio(panel: pd.DataFrame, s: Settings, other: str) -> pd.Series | float:
    """Shrunken per cell ratio that maps another VIIRS platform onto the reference."""
    ref = f"{s.reference_platform}_n_det"
    col = f"{other}_n_det"
    both = panel[ref].notna() & panel[col].notna()
    if both.sum() == 0:
        return None
    sub = panel[both]
    R = sub[ref].sum() / max(sub[col].sum(), 1)
    g = sub.groupby("cell")[[ref, col]].sum()
    k = s.shrinkage_k
    return ((g[ref] + k * R) / (g[col] + k)).rename(f"{other}_to_ref"), R


def fit_all(panel: pd.DataFrame, s: Settings) -> dict:
    feat = add_features(panel)
    ref = f"{s.reference_platform}_n_det"
    models = {}
    for kind in ("aqua", "terra"):
        rows = training_rows(feat, s, kind)
        models[kind] = GBMTransfer(s, kind).fit(feat[rows], feat.loc[rows, ref])
    rows = training_rows(feat, s, "aqua")
    models["baseline"] = RatioBaseline(s).fit(feat[rows], feat.loc[rows, ref])
    rows = training_rows(feat, s, "terra")
    models["baseline_terra"] = TerraRatio(s).fit(feat[rows], feat.loc[rows, ref])
    models["primary"] = s.extra.get("primary_model", "gbm")
    for other in ("NOAA20", "NOAA21"):
        if other != s.reference_platform:
            models[f"xr_{other}"] = viirs_cross_ratio(panel, s, other)
    return models


def harmonize(panel: pd.DataFrame, models: dict, s: Settings) -> pd.DataFrame:
    """Fused series: observed reference VIIRS where available, otherwise the best
    available stand-in, in this order: other VIIRS scaled, Aqua model, Terra model."""
    feat = add_features(panel)
    ref = f"{s.reference_platform}_n_det"
    out = panel[["cell", "cell_lat", "cell_lon", "ym", "year", "month"]].copy()
    h = pd.Series(np.nan, index=feat.index)
    src = pd.Series("", index=feat.index, dtype=object)

    have = feat[ref].notna()
    h[have], src[have] = feat.loc[have, ref], f"VIIRS_{s.reference_platform}_observed"

    for other in ("NOAA20", "NOAA21"):
        xr = models.get(f"xr_{other}")
        if xr is None:
            continue
        ratio, R = xr
        rows = h.isna() & feat[f"{other}_n_det"].notna()
        r = feat.loc[rows, "cell"].map(ratio).fillna(R)
        h[rows] = feat.loc[rows, f"{other}_n_det"] * r
        src[rows] = f"VIIRS_{other}_scaled"

    # Terra gaps inside the Aqua era are handled natively by the gradient boosting model
    use_gbm = models.get("primary", "gbm") == "gbm"
    rows = h.isna() & feat["Aqua_n_det"].notna()
    if rows.any():
        h[rows] = (models["aqua"] if use_gbm else models["baseline"]).predict(feat[rows])
        src[rows] = "MODIS_Aqua+Terra_model"
    rows = h.isna() & feat["Terra_n_det"].notna()
    if rows.any():
        h[rows] = (models["terra"] if use_gbm else models["baseline_terra"]).predict(feat[rows])
        src[rows] = "MODIS_Terra_model"

    out["harmonized"] = h.to_numpy()
    out["source"] = src.to_numpy()
    raw_cols = [c for c in panel.columns if c.endswith("_n_det")]
    out[raw_cols] = panel[raw_cols].to_numpy()
    return out
