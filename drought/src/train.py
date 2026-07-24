"""Eğitim: deterministik LightGBM + zaman bazlı CV.

Çalıştırma (proje kökünden):
    python -m src.train
"""

from __future__ import annotations

import json
import os
import random
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import config as C
from . import cv, dataio, features


def set_global_seed(seed: int = C.SEED) -> None:
    """Determinizm: aynı kod aynı sırayı üretmeli (Zindi kod inceleme şartı)."""
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    np.random.seed(seed)


def prepare() -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Yükle, birleştir, özellik üret, tekrar ayır.

    Özellikleri birleşik veri üzerinde üretmek şart: test satırlarının
    lag'leri train dönemindeki gözlemlerden geliyor.
    """
    train, test = dataio.load_train_test()
    dataio.report(train, "train")
    dataio.report(test, "test")

    combined = pd.concat([train, test], ignore_index=True, sort=False)
    combined = features.build_features(combined)

    feats = features.feature_columns(combined)
    print(f"[features] {len(feats)} özellik üretildi")

    train = combined[~combined["is_test"]].reset_index(drop=True)
    test = combined[combined["is_test"]].reset_index(drop=True)
    return train, test, feats


def _target_arrays(df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Model hedefi ve seviyeye geri çevirmek için gereken offset.

    PREDICT_DELTA açıkken model (TWS_{t+1} - TWS_t) öğrenir; tahmin
    aşamasında TWS_t geri eklenir. Persistence sinyalini modelden çıkarmak
    RMSE'yi tipik olarak belirgin şekilde düşürür.
    """
    cols = C.COLUMNS
    y_level = df[cols.target].to_numpy(dtype="float64")
    offset = df[cols.tws_current].to_numpy(dtype="float64")
    y_model = y_level - offset if C.PREDICT_DELTA else y_level
    return y_model, offset


def run_cv(train: pd.DataFrame, feats: list[str]) -> dict:
    set_global_seed()
    cols = C.COLUMNS

    y_model, offset = _target_arrays(train)
    y_level = train[cols.target].to_numpy(dtype="float64")
    X = train[feats]

    oof = np.full(len(train), np.nan)
    scores: list[dict] = []
    best_iters: list[int] = []

    print(f"\n[baseline] persistence RMSE = {cv.persistence_baseline(train):.5f}")
    print(f"[cv] {C.N_FOLDS} fold, ileri-yönlü zaman bölmesi\n")

    for fold, (tr_idx, va_idx, val_start) in enumerate(cv.time_folds(train)):
        t0 = time.time()
        dtrain = lgb.Dataset(X.iloc[tr_idx], label=y_model[tr_idx], free_raw_data=False)
        dvalid = lgb.Dataset(X.iloc[va_idx], label=y_model[va_idx], free_raw_data=False)

        model = lgb.train(
            C.LGB_PARAMS,
            dtrain,
            num_boost_round=C.NUM_BOOST_ROUND,
            valid_sets=[dvalid],
            callbacks=[
                lgb.early_stopping(C.EARLY_STOPPING_ROUNDS, verbose=False),
                lgb.log_evaluation(500),
            ],
        )

        pred_model = model.predict(X.iloc[va_idx], num_iteration=model.best_iteration)
        pred_level = pred_model + offset[va_idx] if C.PREDICT_DELTA else pred_model
        oof[va_idx] = pred_level

        fold_rmse = cv.rmse(y_level[va_idx], pred_level)
        base_rmse = cv.rmse(y_level[va_idx], offset[va_idx])
        best_iters.append(model.best_iteration)
        scores.append(
            {
                "fold": fold,
                "val_start_t": int(val_start),
                "n_train": len(tr_idx),
                "n_val": len(va_idx),
                "rmse": fold_rmse,
                "persistence_rmse": base_rmse,
                "best_iteration": model.best_iteration,
            }
        )
        print(
            f"  fold {fold}: RMSE={fold_rmse:.5f} (persistence {base_rmse:.5f}, "
            f"kazanç {100 * (1 - fold_rmse / base_rmse):+.1f}%) "
            f"iter={model.best_iteration} [{time.time() - t0:.0f}s]"
        )

        model.save_model(str(C.OUT_DIR / f"lgb_fold{fold}.txt"))

    mask = ~np.isnan(oof)
    overall = cv.rmse(y_level[mask], oof[mask])
    print(f"\n[cv] OOF RMSE = {overall:.5f}")

    breakdown = cv.regional_breakdown(train[mask], y_level[mask], oof[mask])
    print("\n[trustworthiness] enlem kuşağına göre RMSE (rapora gidecek):")
    print(breakdown.to_string())

    np.save(C.OUT_DIR / "oof.npy", oof)
    return {
        "oof_rmse": overall,
        "folds": scores,
        "mean_best_iteration": int(np.mean(best_iters)),
        "n_features": len(feats),
    }


def fit_full(train: pd.DataFrame, feats: list[str], num_round: int) -> lgb.Booster:
    """Tüm train verisiyle son model. Ağaç sayısı CV'den gelen ortalama."""
    set_global_seed()
    y_model, _ = _target_arrays(train)
    dtrain = lgb.Dataset(train[feats], label=y_model)
    model = lgb.train(C.LGB_PARAMS, dtrain, num_boost_round=num_round)
    model.save_model(str(C.OUT_DIR / "lgb_full.txt"))
    return model


def main() -> None:
    C.OUT_DIR.mkdir(parents=True, exist_ok=True)
    train, test, feats = prepare()

    # Hedefi olmayan satırlar eğitime giremez
    train = train[train[C.COLUMNS.target].notna()].reset_index(drop=True)

    result = run_cv(train, feats)
    (C.OUT_DIR / "cv_result.json").write_text(json.dumps(result, indent=2))

    # Ağaç sayısını %10 artır: tam veride biraz daha fazla veri var
    num_round = int(result["mean_best_iteration"] * 1.1)
    model = fit_full(train, feats, num_round)

    imp = pd.DataFrame(
        {
            "feature": model.feature_name(),
            "gain": model.feature_importance("gain"),
        }
    ).sort_values("gain", ascending=False)
    imp.to_csv(C.OUT_DIR / "feature_importance.csv", index=False)
    print("\n[importance] en güçlü 20 özellik:")
    print(imp.head(20).to_string(index=False))

    test[feats].to_parquet(C.OUT_DIR / "test_features.parquet", index=False)
    test[[C.COLUMNS.id, C.COLUMNS.tws_current]].to_parquet(
        C.OUT_DIR / "test_meta.parquet", index=False
    )
    print(f"\n[done] çıktılar: {C.OUT_DIR.resolve()}")


if __name__ == "__main__":
    main()
