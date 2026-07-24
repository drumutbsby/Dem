"""Sentetik veri üreteci — pipeline'ı gerçek veri gelmeden test etmek için.

Gerçek veri setinin varsayılan şemasını taklit eder. Kurulumun çalıştığını
doğrulamak ve kod değişikliklerinden sonra regresyon kontrolü yapmak için:

    python tests/make_synthetic.py /tmp/synth
    DROUGHT_DATA_DIR=/tmp/synth DROUGHT_OUT_DIR=/tmp/synth_out python -m src.train
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(0)

N_LAT, N_LON, N_MONTHS = 12, 14, 40
TEST_MONTHS = 4


def build() -> pd.DataFrame:
    lats = np.round(np.linspace(-30, 30, N_LAT), 2)
    lons = np.round(np.linspace(-20, 40, N_LON), 2)
    dates = pd.date_range("2018-01-01", periods=N_MONTHS, freq="MS")

    grid = pd.MultiIndex.from_product(
        [lats, lons, dates], names=["lat", "lon", "date"]
    ).to_frame(index=False)

    n_cells = N_LAT * N_LON
    cell_key = grid.groupby(["lat", "lon"], sort=False).ngroup().to_numpy()
    month_idx = grid["date"].dt.month.to_numpy()
    t = grid.groupby(["lat", "lon"], sort=False).cumcount().to_numpy()

    # Hücre bazlı taban seviye + mevsimsellik + trend + gürültü
    base = RNG.normal(0, 10, n_cells)[cell_key]
    seasonal = 6 * np.sin(2 * np.pi * month_idx / 12 + cell_key % 5)
    trend = -0.05 * t * (cell_key % 3 == 0)
    noise = RNG.normal(0, 1.5, len(grid))
    tws = base + seasonal + trend + noise

    grid["TWS_t"] = tws.astype("float32")
    for scale in range(1, 13):
        grid[f"SPEI_{scale}"] = (
            RNG.normal(0, 1, len(grid)) - 0.02 * scale * (trend < 0)
        ).astype("float32")
    grid["soil_moisture"] = (0.3 + 0.01 * tws + RNG.normal(0, 0.05, len(grid))).astype(
        "float32"
    )

    # Hedef: aynı hücrenin bir sonraki ayki TWS'i
    grid = grid.sort_values(["lat", "lon", "date"]).reset_index(drop=True)
    grid["target"] = grid.groupby(["lat", "lon"], sort=False)["TWS_t"].shift(-1)
    grid["ID"] = [f"ID_{i:07d}" for i in range(len(grid))]
    return grid


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/synth")
    out.mkdir(parents=True, exist_ok=True)

    df = build().dropna(subset=["target"]).reset_index(drop=True)
    cutoff = df["date"].sort_values().unique()[-TEST_MONTHS]

    train = df[df["date"] < cutoff].reset_index(drop=True)
    test = df[df["date"] >= cutoff].reset_index(drop=True)

    train.to_csv(out / "Train.csv", index=False)
    test.drop(columns=["target"]).to_csv(out / "Test.csv", index=False)
    test[["ID"]].assign(target=0.0).to_csv(out / "SampleSubmission.csv", index=False)

    print(f"train={len(train):,} test={len(test):,} -> {out}")


if __name__ == "__main__":
    main()
