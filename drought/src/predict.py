"""Submission üretimi.

Çalıştırma:
    python -m src.predict            # fold modellerinin ortalaması (önerilen)
    python -m src.predict --full     # tam veriyle eğitilmiş tek model
"""

from __future__ import annotations

import argparse
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from . import config as C


def _load_models(use_full: bool) -> list[lgb.Booster]:
    if use_full:
        path = C.OUT_DIR / "lgb_full.txt"
        if not path.exists():
            raise FileNotFoundError(f"{path} yok — önce `python -m src.train` çalıştır.")
        return [lgb.Booster(model_file=str(path))]

    paths = sorted(C.OUT_DIR.glob("lgb_fold*.txt"))
    if not paths:
        raise FileNotFoundError(
            f"{C.OUT_DIR} içinde fold modeli yok — önce `python -m src.train` çalıştır."
        )
    return [lgb.Booster(model_file=str(p)) for p in paths]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--full", action="store_true", help="tam-veri modelini kullan")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    cols = C.COLUMNS
    X_test = pd.read_parquet(C.OUT_DIR / "test_features.parquet")
    meta = pd.read_parquet(C.OUT_DIR / "test_meta.parquet")

    models = _load_models(args.full)
    preds = np.mean([m.predict(X_test) for m in models], axis=0)

    if C.PREDICT_DELTA:
        preds = preds + meta[cols.tws_current].to_numpy(dtype="float64")

    sub = pd.DataFrame({cols.id: meta[cols.id], cols.target: preds})

    # Sample submission varsa satır sırasını ona hizala — Zindi sıra/ID uyumsuzluğunda
    # dosyayı reddediyor ve o submission hakkın yanmasa da vakit kaybettiriyor.
    template_path = C.DATA_DIR / C.SUBMISSION_TEMPLATE
    if template_path.exists():
        template = pd.read_csv(template_path)
        sub = template[[cols.id]].merge(sub, on=cols.id, how="left")
        missing = sub[cols.target].isna().sum()
        if missing:
            raise ValueError(
                f"{missing} ID için tahmin üretilemedi — test özellikleri eksik."
            )

    out = args.out or (C.OUT_DIR / "submission.csv")
    sub.to_csv(out, index=False)
    print(f"[submission] {len(sub):,} satır -> {out}")
    print(sub.describe().to_string())


if __name__ == "__main__":
    main()
