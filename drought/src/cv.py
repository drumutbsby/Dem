"""Zaman bazlı doğrulama.

Bu yarışmada rastgele KFold kullanmak en yaygın ve en pahalı hata:
aynı hücrenin komşu aylarını hem train hem validation'a dağıtır, lokal
skoru şişirir ve private leaderboard'da (test'in %70'i) çöker. Burada
sadece ileri-yönlü (rolling-origin) bölme yapıyoruz.
"""

from __future__ import annotations

from typing import Iterator

import numpy as np
import pandas as pd

from . import config as C


def time_folds(
    df: pd.DataFrame,
    n_folds: int = C.N_FOLDS,
    val_months: int = C.VAL_MONTHS_PER_FOLD,
    gap: int = C.GAP_MONTHS,
) -> Iterator[tuple[np.ndarray, np.ndarray, int]]:
    """Rolling-origin bölme.

    Fold 0 en eski, son fold en yeni dönemi doğrular. Her fold'da train
    daima validation'dan ÖNCEKİ aylardan oluşur.
    """
    t = df["t"].to_numpy()
    t_max = int(t.max())

    for i in range(n_folds):
        val_end = t_max - (n_folds - 1 - i) * val_months
        val_start = val_end - val_months + 1
        train_end = val_start - 1 - gap

        train_idx = np.where(t <= train_end)[0]
        val_idx = np.where((t >= val_start) & (t <= val_end))[0]

        if len(train_idx) == 0 or len(val_idx) == 0:
            continue
        yield train_idx, val_idx, val_start


def rmse(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    mask = ~np.isnan(y_true)
    return float(np.sqrt(np.mean((y_true[mask] - y_pred[mask]) ** 2)))


def persistence_baseline(df: pd.DataFrame) -> float:
    """TWS_{t+1} = TWS_t baseline'ı.

    Her modelin geçmesi gereken taban çizgisi. Buna yakın bir skor
    alıyorsan model aslında hiçbir şey öğrenmiyor demektir.
    """
    cols = C.COLUMNS
    return rmse(
        df[cols.target].to_numpy(dtype="float64"),
        df[cols.tws_current].to_numpy(dtype="float64"),
    )


def regional_breakdown(
    df: pd.DataFrame, y_true: np.ndarray, y_pred: np.ndarray, n_bands: int = 6
) -> pd.DataFrame:
    """Enlem kuşaklarına göre RMSE dağılımı.

    Rapordaki 'AI trustworthiness' bölümü için doğrudan malzeme: modelin
    hangi coğrafyada zayıf olduğunu göstermek rubrikte puan getiriyor.
    """
    cols = C.COLUMNS
    bands = pd.cut(df[cols.lat], bins=n_bands)
    out = (
        pd.DataFrame({"band": bands, "err": (y_true - y_pred) ** 2})
        .groupby("band", observed=True)["err"]
        .agg(["mean", "count"])
    )
    out["rmse"] = np.sqrt(out["mean"])
    return out[["rmse", "count"]].sort_values("rmse", ascending=False)
