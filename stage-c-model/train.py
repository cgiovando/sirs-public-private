"""Stage C v0.1 - calibrated binary public-vs-private classifier for Benin.

Why binary, not 7-class:
- Stage A only has high-confidence positives in two classes that matter for the
  SIRS public-stock rollup: public vs (private-secular OR private-religious OR
  community).
- 7-class with 1 community example would be a degenerate fit.
- Future work: multiclass once Mali / Niger / Guinea expand the labelled set.

Pipeline:
- Train set: Stage A high-confidence labels only, dropping unknown/medium/low.
- Features: distance + density + worship + GHSL SMOD class (one-hot) + RWI.
- Model: LogisticRegression(class_weight='balanced') wrapped in
  CalibratedClassifierCV(method='isotonic', cv=5). Logistic over Boosting for
  v0.1 because (a) we want interpretable coefficients to discuss in the meeting
  and (b) the labelled set is biased urban; a complex model would overfit
  exactly where we already do well.
- Evaluation: 5-fold CV on train, report ROC-AUC and Brier; calibration plot.
- Inference: predict on the FULL feature matrix (including the 2,732 unknowns
  Stage A punted on). Output probabilities + a class with `unknown_band`
  surfaced when 0.30 < p < 0.70.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV, calibration_curve
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


PRIVATE_LABELS = {"private-secular", "private-religious", "community"}
NUMERIC_FEATURES = [
    "dist_to_cotonou_km",
    "dist_to_nearest_major_city_km",
    "schools_within_1km",
    "schools_within_5km",
    "dist_to_nearest_school_m",
    "dist_to_mosque_m",
    "dist_to_church_m",
    "dist_to_any_worship_m",
    "worship_within_500m",
    "rwi",
]
CATEGORICAL_FEATURES = ["smod_class", "nearest_major_city"]


def label_target(df: pd.DataFrame) -> pd.Series:
    """1 = private (any), 0 = public, NaN = unknown / not high-conf."""
    y = pd.Series(np.nan, index=df.index, dtype=float)
    high = df["ownership_confidence"] == "high"
    y.loc[high & (df["ownership_label"] == "public")] = 0.0
    y.loc[high & df["ownership_label"].isin(PRIVATE_LABELS)] = 1.0
    return y


def make_pipeline() -> Pipeline:
    pre = ColumnTransformer(
        transformers=[
            ("num", StandardScaler(), NUMERIC_FEATURES),
            ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ],
        remainder="drop",
    )
    base = LogisticRegression(
        class_weight="balanced",
        max_iter=1000,
        solver="liblinear",
        random_state=0,
    )
    cal = CalibratedClassifierCV(base, method="isotonic", cv=5)
    return Pipeline([("pre", pre), ("clf", cal)])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--features", required=True)
    p.add_argument("--output", required=True, help="parquet with predictions for all rows")
    p.add_argument("--metrics", required=True, help="JSON metrics output")
    args = p.parse_args()

    df = pd.read_parquet(args.features)
    df = df.dropna(subset=NUMERIC_FEATURES + CATEGORICAL_FEATURES).reset_index(drop=True)
    y = label_target(df)
    is_train = y.notna()
    n_train = int(is_train.sum())
    n_priv = int((y == 1).sum())
    n_pub = int((y == 0).sum())
    print(f"training rows: {n_train}  (public={n_pub}, private={n_priv})")
    print(f"inference rows (incl. unknowns): {len(df)}")

    pipe = make_pipeline()
    X_train = df.loc[is_train].copy()
    y_train = y[is_train].values

    # Cross-val predictions: shuffled stratified folds AND ADM1-grouped folds.
    # The shuffled number is what most ML reports use; the grouped number is
    # the honest one for spatial data because nearby schools are correlated
    # (Codex review flagged this as the priority statistical fix).
    cv_shuffled = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)
    cv_proba = cross_val_predict(pipe, X_train, y_train, cv=cv_shuffled, method="predict_proba")[:, 1]
    auc = float(roc_auc_score(y_train, cv_proba))
    brier = float(brier_score_loss(y_train, cv_proba))
    pred_share_priv = float((cv_proba >= 0.5).mean())
    print(f"shuffled 5-fold CV ROC-AUC: {auc:.3f}")
    print(f"shuffled 5-fold CV Brier:   {brier:.3f}")

    # ADM1-grouped CV (12 Benin departments). Schools in the same department
    # share OSM coverage patterns, naming conventions, and urban form, so
    # grouped CV stops the model from memorising those local patterns.
    groups_train = X_train["adm1"].fillna("UNKNOWN").values
    n_groups = len(set(groups_train))
    n_splits_g = min(5, n_groups)
    if n_splits_g >= 2:
        cv_grouped = GroupKFold(n_splits=n_splits_g)
        cv_proba_g = cross_val_predict(
            pipe, X_train, y_train, cv=cv_grouped, groups=groups_train, method="predict_proba"
        )[:, 1]
        auc_g = float(roc_auc_score(y_train, cv_proba_g))
        brier_g = float(brier_score_loss(y_train, cv_proba_g))
        print(f"ADM1-grouped {n_splits_g}-fold CV ROC-AUC: {auc_g:.3f}")
        print(f"ADM1-grouped {n_splits_g}-fold CV Brier:   {brier_g:.3f}")
    else:
        auc_g = brier_g = float("nan")
        cv_proba_g = None
        n_splits_g = 0

    # Calibration curve uses the shuffled-fold predictions (the curve is a
    # diagnostic of the calibrator, not a generalisation estimate).
    frac_pos, mean_pred = calibration_curve(y_train, cv_proba, n_bins=10, strategy="quantile")

    # Final fit on the full training set, predict on everything (incl. unknowns).
    pipe.fit(X_train, y_train)
    full_proba = pipe.predict_proba(df)[:, 1]

    df_out = df.copy()
    df_out["stage_c_p_private"] = np.round(full_proba, 4)
    df_out["stage_c_class"] = np.where(full_proba >= 0.5, "private", "public")
    df_out["stage_c_band"] = pd.cut(
        full_proba,
        bins=[-0.001, 0.30, 0.70, 1.001],
        labels=["likely-public", "uncertain", "likely-private"],
    )

    # Prior-shift adjustment.
    # The model is calibrated to the labelled training prior (training rate of
    # private). For population-level inference we want probabilities that
    # target each department's INFRE 2021-22 primary private rate. Apply
    # Saerens-Latinne-Decaestecker prior shift per row using the school's
    # ADM1 prior. Unknown ADM1 falls back to the national INFRE figure.
    train_prior = float((y_train == 1).mean())
    df_out["train_prior"] = round(train_prior, 4)
    priors_path = Path(__file__).parent.parent / "data/cache/infre/benin_dept_priors_2021_2022.parquet"
    if priors_path.exists():
        priors = pd.read_parquet(priors_path)
        national_prior = float(priors["n_schools_private"].sum() / priors["n_schools_total"].sum())
        adm1_to_prior = dict(zip(priors["department"], priors["private_share"]))
        df_out["dept_prior_private"] = df_out["adm1"].map(adm1_to_prior).fillna(national_prior).round(4)
    else:
        national_prior = 0.17  # legacy fallback
        df_out["dept_prior_private"] = national_prior

    p_old = df_out["stage_c_p_private"].clip(1e-6, 1 - 1e-6).values
    pi_old = train_prior
    pi_new = df_out["dept_prior_private"].values
    # Saerens-Latinne-Decaestecker:
    #   p_new = (p_old * pi_new/pi_old) / [p_old * pi_new/pi_old + (1-p_old) * (1-pi_new)/(1-pi_old)]
    num = p_old * (pi_new / pi_old)
    den = num + (1 - p_old) * ((1 - pi_new) / (1 - pi_old))
    df_out["stage_c_p_private_adj"] = np.round(num / den, 4)
    df_out["stage_c_band_adj"] = pd.cut(
        df_out["stage_c_p_private_adj"],
        bins=[-0.001, 0.30, 0.70, 1.001],
        labels=["likely-public", "uncertain", "likely-private"],
    )

    # Surface two "final" labels:
    #   ownership_final     - conservative; uses the labelled-set-calibrated
    #                         probability. Better when we trust Stage A and
    #                         want to admit "unknown" rather than over-predict
    #                         private.
    #   ownership_final_adj - prior-shifted; uses each school's department
    #                         INFRE prior. Better as a population-level
    #                         estimate to compare against external aggregates.
    # Stage A labels (high AND medium confidence) are preserved as-is in both;
    # Stage C only fills in genuine unknowns.
    is_unknown = df_out["ownership_label"] == "unknown"

    final = df_out["ownership_label"].copy()
    final.loc[is_unknown & (df_out["stage_c_band"] == "likely-private")] = "private-model"
    final.loc[is_unknown & (df_out["stage_c_band"] == "likely-public")] = "public-model"
    final.loc[is_unknown & (df_out["stage_c_band"] == "uncertain")] = "uncertain"
    df_out["ownership_final"] = final

    final_adj = df_out["ownership_label"].copy()
    final_adj.loc[is_unknown & (df_out["stage_c_band_adj"] == "likely-private")] = "private-model"
    final_adj.loc[is_unknown & (df_out["stage_c_band_adj"] == "likely-public")] = "public-model"
    final_adj.loc[is_unknown & (df_out["stage_c_band_adj"] == "uncertain")] = "uncertain"
    df_out["ownership_final_adj"] = final_adj
    # Flag medium-confidence Stage A rows where the model strongly disagrees
    # (>=0.30 probability gap). These belong in the manual-review queue.
    is_medium = df_out["ownership_confidence"] == "medium"
    stage_a_priv = df_out["ownership_label"].isin(["private-secular", "private-religious", "community"])
    stage_a_pub = df_out["ownership_label"] == "public"
    df_out["model_agreement"] = "n/a"
    df_out.loc[is_medium & stage_a_priv & (df_out["stage_c_p_private"] < 0.30), "model_agreement"] = "model_disagrees_pub"
    df_out.loc[is_medium & stage_a_pub & (df_out["stage_c_p_private"] > 0.70), "model_agreement"] = "model_disagrees_priv"
    df_out.loc[is_medium & ~df_out["model_agreement"].str.startswith("model_disagrees"), "model_agreement"] = "ok"

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df_out.to_parquet(args.output, index=False)
    print(f"wrote predictions -> {args.output}")

    # Feature importance (signed coefficients from the underlying logistic model).
    # Calibrated wrapper holds K calibrated_classifiers_ with a base_estimator each.
    coefs = []
    for cc in pipe.named_steps["clf"].calibrated_classifiers_:
        est = cc.estimator
        coefs.append(est.coef_[0])
    coef_mean = np.mean(coefs, axis=0)
    feat_names = pipe.named_steps["pre"].get_feature_names_out().tolist()
    imp = pd.DataFrame({"feature": feat_names, "coef_mean": coef_mean})
    imp = imp.reindex(imp["coef_mean"].abs().sort_values(ascending=False).index)
    print("\nTop signed coefficients (positive = pushes toward private):")
    print(imp.head(15).to_string(index=False))

    metrics = {
        "n_train": n_train,
        "n_public_train": n_pub,
        "n_private_train": n_priv,
        "n_inference": int(len(df)),
        "cv_shuffled_roc_auc": auc,
        "cv_shuffled_brier": brier,
        "cv_grouped_adm1_roc_auc": auc_g,
        "cv_grouped_adm1_brier": brier_g,
        "cv_grouped_n_splits": n_splits_g,
        "cv_roc_auc": auc,  # back-compat
        "cv_brier": brier,  # back-compat
        "cv_predicted_private_share": pred_share_priv,
        "train_prior_private": train_prior,
        "calibration_curve": {
            "mean_predicted": [float(x) for x in mean_pred],
            "fraction_positive": [float(x) for x in frac_pos],
        },
        "feature_importance": imp.to_dict(orient="records"),
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=Path(__file__).parent.parent
        ).decode().strip() if Path(".git").exists() else "unknown",
        "runtime_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    Path(args.metrics).parent.mkdir(parents=True, exist_ok=True)
    Path(args.metrics).write_text(json.dumps(metrics, indent=2))
    print(f"wrote metrics -> {args.metrics}")


if __name__ == "__main__":
    main()
