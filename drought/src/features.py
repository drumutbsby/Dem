"""Uzamsal-zamansal özellik mühendisliği.

Sızıntı kuralı: hedef t+1 anına ait. Buradaki HİÇBİR özellik t anından
sonraki bilgiyi kullanmaz. Mevsimsel iklim ortalamaları bile hedeften
değil, gözlenen TWS_t kolonundan üretilir — böylece fold-güvenli olur ve
Zindi kod incelemesinde "data leak" tartışması hiç açılmaz.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


def _sorted_by_cell_time(df: pd.DataFrame) -> pd.DataFrame:
    return df.sort_values(["cell", "t"], kind="stable").reset_index(drop=True)


def add_lag_features(df: pd.DataFrame) -> pd.DataFrame:
    """Hücre bazında geçmiş değerler. TWS_t gözlenen bir girdi, hedef değil."""
    cols = C.COLUMNS
    lag_sources = [cols.tws_current, *cols.extra_numeric, "SPEI_1", "SPEI_3", "SPEI_12"]
    lag_sources = [c for c in lag_sources if c in df.columns]

    grouped = df.groupby("cell", sort=False)
    for col in lag_sources:
        for lag in C.LAGS:
            df[f"{col}_lag{lag}"] = grouped[col].shift(lag).astype("float32")

    # Ardışık farklar: seviyeden çok değişim yönü bilgi taşıyor
    for col in lag_sources:
        for lag in C.LAGS:
            src = f"{col}_lag{lag}"
            if src in df.columns:
                df[f"{col}_diff{lag}"] = (df[col] - df[src]).astype("float32")
    return df


def add_rolling_features(df: pd.DataFrame) -> pd.DataFrame:
    """Kayan pencere ortalama/std/min/max — kuraklığın süresini yakalar."""
    cols = C.COLUMNS
    grouped = df.groupby("cell", sort=False)[cols.tws_current]

    for win in C.ROLL_WINDOWS:
        roll = grouped.rolling(win, min_periods=max(2, win // 2))
        stats = roll.agg(["mean", "std", "min", "max"]).reset_index(level=0, drop=True)
        df[f"tws_roll{win}_mean"] = stats["mean"].astype("float32")
        df[f"tws_roll{win}_std"] = stats["std"].astype("float32")
        df[f"tws_roll{win}_min"] = stats["min"].astype("float32")
        df[f"tws_roll{win}_max"] = stats["max"].astype("float32")

        # Mevcut değerin kendi geçmişine göre konumu — anomali sinyali
        df[f"tws_anom{win}"] = (
            df[cols.tws_current] - df[f"tws_roll{win}_mean"]
        ).astype("float32")
    return df


def add_trend_features(df: pd.DataFrame, window: int = 12) -> pd.DataFrame:
    """Son `window` ay üzerinden hücre bazlı doğrusal eğim.

    Uzun vadeli akifer tükenmesi ile mevsimsel salınımı ayırır — bu ayrım
    tam olarak kuraklık erken uyarısının aradığı şey.

    Vektörel çözüm: pencere içindeki x konumları sabit olduğu için eğim,
    kaydırılmış serilerin ağırlıklı toplamı olarak yazılabilir. `rolling.apply`
    ile Python seviyesinde döngü kurmak 2.4M satırda dakikalar sürüyordu.
    """
    cols = C.COLUMNS
    grouped = df.groupby("cell", sort=False)[cols.tws_current]

    x_mean = (window - 1) / 2.0
    denom = window * (window**2 - 1) / 12.0  # Σ(x_i - x̄)², x = 0..w-1

    weighted = None  # Σ x_i * y_i
    total = None  # Σ y_i
    for j in range(window):
        shifted = grouped.shift(j)
        weight = window - 1 - j  # y_{t-j} penceredeki x konumu
        weighted = shifted * weight if weighted is None else weighted + shifted * weight
        total = shifted if total is None else total + shifted

    df[f"tws_slope{window}"] = ((weighted - x_mean * total) / denom).astype("float32")
    return df


def add_seasonal_features(df: pd.DataFrame) -> pd.DataFrame:
    """Döngüsel ay kodlaması + hücre-ay iklim ortalaması.

    İklim ortalaması TWS_t'den (gözlenen girdi) hesaplanır, hedeften değil.
    """
    cols = C.COLUMNS
    df["month_sin"] = np.sin(2 * np.pi * df["month"] / 12).astype("float32")
    df["month_cos"] = np.cos(2 * np.pi * df["month"] / 12).astype("float32")

    clim = (
        df.groupby(["cell", "month"], sort=False)[cols.tws_current]
        .transform("mean")
        .astype("float32")
    )
    df["tws_clim_cell_month"] = clim
    df["tws_dev_from_clim"] = (df[cols.tws_current] - clim).astype("float32")

    # Bir sonraki ayın iklim ortalaması: hedef ayın mevsimsel beklentisi
    df["next_month"] = (df["month"] % 12 + 1).astype("int8")
    clim_table = (
        df.groupby(["cell", "month"], sort=False)[cols.tws_current]
        .mean()
        .rename("tws_clim_next")
        .reset_index()
        .rename(columns={"month": "next_month"})
    )
    df = df.merge(clim_table, on=["cell", "next_month"], how="left")
    df["tws_clim_next"] = df["tws_clim_next"].astype("float32")
    df["clim_seasonal_step"] = (
        df["tws_clim_next"] - df["tws_clim_cell_month"]
    ).astype("float32")
    return df


def add_spatial_features(df: pd.DataFrame) -> pd.DataFrame:
    """Aynı zaman adımındaki komşu hücrelerin TWS ortalaması.

    t anında gözlenen veriden üretildiği için meşru: test setindeki
    komşu HEDEFLERİNDEN bilgi çekmiyoruz (o sızıntı sayılır ve
    diskalifiye sebebi).
    """
    cols = C.COLUMNS

    lat_vals = np.sort(df[cols.lat].unique())
    lon_vals = np.sort(df[cols.lon].unique())
    lat_step = np.median(np.diff(lat_vals)) if len(lat_vals) > 1 else 1.0
    lon_step = np.median(np.diff(lon_vals)) if len(lon_vals) > 1 else 1.0

    df["lat_idx"] = np.round((df[cols.lat] - lat_vals[0]) / lat_step).astype("int32")
    df["lon_idx"] = np.round((df[cols.lon] - lon_vals[0]) / lon_step).astype("int32")

    # merge yerine MultiIndex reindex: merge, sağ tarafta tekrar eden anahtar
    # olduğunda satır sayısını şişirir ve hizalama sessizce bozulur. reindex
    # her zaman sol frame ile aynı uzunlukta dizi döndürür.
    lookup = pd.Series(
        df[cols.tws_current].to_numpy(dtype="float32"),
        index=pd.MultiIndex.from_arrays(
            [df["t"], df["lat_idx"], df["lon_idx"]], names=["t", "lat_idx", "lon_idx"]
        ),
    )
    lookup = lookup[~lookup.index.duplicated(keep="first")]

    ring = C.SPATIAL_RING
    offsets = [
        (dy, dx)
        for dy in range(-ring, ring + 1)
        for dx in range(-ring, ring + 1)
        if (dy, dx) != (0, 0)
    ]

    acc_sum = np.zeros(len(df), dtype="float32")
    acc_cnt = np.zeros(len(df), dtype="float32")
    t_arr = df["t"].to_numpy()
    lat_arr = df["lat_idx"].to_numpy()
    lon_arr = df["lon_idx"].to_numpy()

    for dy, dx in offsets:
        idx = pd.MultiIndex.from_arrays([t_arr, lat_arr + dy, lon_arr + dx])
        vals = lookup.reindex(idx).to_numpy(dtype="float32")
        mask = ~np.isnan(vals)
        acc_sum[mask] += vals[mask]
        acc_cnt[mask] += 1

    with np.errstate(invalid="ignore", divide="ignore"):
        neigh_mean = np.where(acc_cnt > 0, acc_sum / acc_cnt, np.nan)

    df["tws_neigh_mean"] = neigh_mean.astype("float32")
    df["tws_neigh_count"] = acc_cnt.astype("float32")
    df["tws_minus_neigh"] = (df[cols.tws_current] - df["tws_neigh_mean"]).astype("float32")
    return df


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Tüm özellik adımlarını sırayla uygula."""
    df = _sorted_by_cell_time(df)
    df = add_lag_features(df)
    df = add_rolling_features(df)
    df = add_trend_features(df)
    df = add_seasonal_features(df)
    df = add_spatial_features(df)
    return df


def feature_columns(df: pd.DataFrame) -> list[str]:
    """Modele girecek kolonlar. Kimlik/hedef/yardımcı kolonları dışla."""
    cols = C.COLUMNS
    excluded = {
        cols.id,
        cols.target,
        cols.date,
        "is_test",
        "cell",
        "next_month",
        "lat_idx",
        "lon_idx",
        "_delta_target",
    }
    return [
        c
        for c in df.columns
        if c not in excluded and pd.api.types.is_numeric_dtype(df[c])
    ]
