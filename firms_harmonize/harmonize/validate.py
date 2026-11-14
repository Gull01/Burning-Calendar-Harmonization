"""Leave one year out validation inside the MODIS / VIIRS overlap period."""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import Settings
from .model import GBMTransfer, RatioBaseline, add_features, training_rows


def _metrics(obs: np.ndarray, pred: np.ndarray) -> dict:
    obs, pred = np.asarray(obs, float), np.asarray(pred, float)
    bias = (pred.sum() - obs.sum()) / max(obs.sum(), 1e-9) * 100
    r = np.corrcoef(obs, pred)[0, 1] if obs.std() > 0 and pred.std() > 0 else np.nan
    r_log = np.corrcoef(np.log1p(obs), np.log1p(pred))[0, 1] if obs.std() > 0 else np.nan
    return {
        "n": len(obs),
        "pearson_r": round(float(r), 3),
        "pearson_r_log1p": round(float(r_log), 3),
        "mae": round(float(np.abs(obs - pred).mean()), 3),
        "bias_pct": round(float(bias), 2),
    }


def leave_one_year_out(panel: pd.DataFrame, s: Settings, max_folds: int | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train on all overlap years but one, predict the held out year.

    Returns (predictions per cell-month, metrics table). Only complete calendar
    years inside the overlap are used as test folds. For large countries,
    `max_folds` tests an evenly spread sample of years instead of every year.
    """
    feat = add_features(panel)
    ref = f"{s.reference_platform}_n_det"
    rows = training_rows(feat, s, "aqua")
    data = feat[rows]
    months_per_year = data.groupby("year").ym.nunique()
    years = sorted(months_per_year[months_per_year == 12].index)
    if max_folds and len(years) > max_folds:
        pick = np.unique(np.round(np.linspace(0, len(years) - 1, max_folds)).astype(int))
        years = [years[k] for k in pick]

    preds = []
    for yr in years:
        tr, te = data[data.year != yr], data[data.year == yr]
        y_tr = tr[ref]
        p = te[["cell", "ym", "year", "month", ref, "Aqua_n_det", "Terra_n_det"]].copy()
        p["pred_gbm_aqua"] = GBMTransfer(s, "aqua").fit(tr, y_tr).predict(te)
        p["pred_gbm_terra"] = GBMTransfer(s, "terra").fit(tr, y_tr).predict(te)
        p["pred_ratio"] = RatioBaseline(s).fit(tr, y_tr).predict(te)
        preds.append(p)
        print(f"    held out {yr}: done")
    preds = pd.concat(preds, ignore_index=True)

    rows = []
    for name in ("pred_gbm_aqua", "pred_gbm_terra", "pred_ratio"):
        cm = _metrics(preds[ref], preds[name])
        cm.update(model=name, scale="cell-month")
        rows.append(cm)
        reg = preds.groupby("ym")[[ref, name]].sum()
        rm = _metrics(reg[ref], reg[name])
        rm.update(model=name, scale="region-month")
        rows.append(rm)
        ann = preds.groupby("year")[[ref, name]].sum()
        am = _metrics(ann[ref], ann[name])
        am.update(model=name, scale="region-year")
        rows.append(am)
    metrics = pd.DataFrame(rows)[
        ["model", "scale", "n", "pearson_r", "pearson_r_log1p", "mae", "bias_pct"]
    ]
    return preds, metrics


def by_year(preds: pd.DataFrame, s: Settings, col: str = "pred_gbm_aqua") -> pd.DataFrame:
    """Observed vs predicted annual totals and bias for each held-out year."""
    ref = f"{s.reference_platform}_n_det"
    g = preds.groupby("year")[[ref, col]].sum().rename(columns={ref: "observed", col: "predicted"})
    g["bias_pct"] = ((g.predicted / g.observed - 1) * 100).round(1)
    return g.round(0)


def backcast_test(panel: pd.DataFrame, s: Settings, n_test_years: int = 4) -> tuple[pd.DataFrame, dict]:
    """The test that mirrors how the model is used.

    The model reconstructs 2000 to 2011 from relationships learned later. Here we
    train only on the later overlap years and predict the first `n_test_years`
    VIIRS years, which the model never saw, in the same backward direction.
    """
    feat = add_features(panel)
    ref = f"{s.reference_platform}_n_det"
    data = feat[training_rows(feat, s, "aqua")]
    months_per_year = data.groupby("year").ym.nunique()
    years = sorted(months_per_year[months_per_year == 12].index)
    test_years = years[:n_test_years]
    tr = data[data.year > max(test_years)]
    te = data[data.year.isin(test_years)]
    p = te[["ym", "year", ref]].copy()
    p["pred_gbm_aqua"] = GBMTransfer(s, "aqua").fit(tr, tr[ref]).predict(te)
    p["pred_ratio"] = RatioBaseline(s).fit(tr, tr[ref]).predict(te)
    out = {"train_years": f"{tr.year.min()} to {tr.year.max()}",
           "test_years": f"{min(test_years)} to {max(test_years)}"}
    for name in ("pred_gbm_aqua", "pred_ratio"):
        reg = p.groupby("ym")[[ref, name]].sum()
        out[name] = _metrics(reg[ref], reg[name])
    g, r = by_year(p, s, "pred_gbm_aqua"), by_year(p, s, "pred_ratio")
    years = pd.DataFrame({"observed": g.observed, "predicted_gbm": g.predicted, "bias_pct_gbm": g.bias_pct,
                          "predicted_ratio": r.predicted, "bias_pct_ratio": r.bias_pct})
    return years, out
