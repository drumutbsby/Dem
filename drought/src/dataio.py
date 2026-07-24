"""Veri yükleme, tip küçültme ve şema doğrulama.

2.15M satır × ~20 kolon float32'de ~2-3 GB tutar. 251 GB RAM'in avantajı
veriyi sığdırmak değil, paralel deney koşturmak — bu yüzden pipeline'ı
16 GB'ta dönecek şekilde tutuyoruz (Zindi hakem makinesinde çalışmalı).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C

# Bazı Zindi veri setlerinde eksik değer sentinel ile işaretlenir.
SENTINELS = (-9999, -999, -9999.0)


def _downcast(df: pd.DataFrame) -> pd.DataFrame:
    """float64 -> float32, int64 -> en küçük uygun int. Belleği ~yarıya indirir."""
    for col in df.select_dtypes(include=["float64"]).columns:
        df[col] = df[col].astype("float32")
    for col in df.select_dtypes(include=["int64"]).columns:
        df[col] = pd.to_numeric(df[col], downcast="integer")
    return df


def _clean_sentinels(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Sentinel eksik-değer kodlarını NaN'a çevir.

    Bunu atlamak felakettir: -9999 gerçek bir değer sanılıp ağaçların
    split noktalarını tamamen bozar.
    """
    for col in cols:
        if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].mask(df[col].isin(SENTINELS))
    return df


def validate_schema(df: pd.DataFrame, name: str, *, require_target: bool) -> None:
    """Beklenen kolonlar yoksa sessizce devam etme — yüksek sesle hata ver."""
    cols = C.COLUMNS
    expected = [cols.lat, cols.lon, cols.date, *cols.raw_features]
    if require_target:
        expected.append(cols.target)

    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise KeyError(
            f"[{name}] config.Columns ile veri uyuşmuyor.\n"
            f"  Eksik kolonlar: {missing}\n"
            f"  Dosyadaki kolonlar: {list(df.columns)}\n"
            f"  -> src/config.py içindeki Columns sınıfını gerçek isimlerle güncelle."
        )


def add_time_index(df: pd.DataFrame) -> pd.DataFrame:
    """Tarihi MUTLAK aylık tam sayıya çevir (year*12 + month).

    Burada sıfırlama yapılmıyor. Normalizasyon train+test birleştirildikten
    sonra tek seferde yapılmalı: her dosyayı kendi minimumuna göre sıfırlarsak
    test t=[0,3], train t=[0,34] olur, iki zaman ekseni üst üste biner ve
    lag/komşuluk özellikleri sessizce yanlış hesaplanır.
    """
    cols = C.COLUMNS
    dt = pd.to_datetime(df[cols.date])
    df["year"] = dt.dt.year.astype("int16")
    df["month"] = dt.dt.month.astype("int8")
    df["t_abs"] = (dt.dt.year * 12 + dt.dt.month).astype("int32")
    return df


def add_cell_id(df: pd.DataFrame) -> pd.DataFrame:
    """(lat, lon) çiftini tek bir hücre kimliğine indir — groupby bunun üstünde döner."""
    cols = C.COLUMNS
    key = (
        df[cols.lat].round(4).astype(str) + "_" + df[cols.lon].round(4).astype(str)
    )
    df["cell"] = pd.factorize(key)[0].astype("int32")
    return df


def load(name: str, *, require_target: bool) -> pd.DataFrame:
    path = C.DATA_DIR / name
    df = pd.read_csv(path)
    validate_schema(df, name, require_target=require_target)
    df = _clean_sentinels(df, list(df.columns))
    df = _downcast(df)
    df = add_time_index(df)
    return df


def load_train_test() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Train ve test'i yükleyip ORTAK hücre indeksiyle döndür.

    Hücre kimliğini birleşik veri üzerinden üretmek şart: aksi halde test'teki
    hücre id'leri train'dekilerle eşleşmez ve lag özellikleri boşa çıkar.
    """
    train = load(C.TRAIN_FILE, require_target=True)
    test = load(C.TEST_FILE, require_target=False)

    train["is_test"] = False
    test["is_test"] = True

    combined = pd.concat([train, test], ignore_index=True, sort=False)
    combined = add_cell_id(combined)

    # Zaman eksenini TEK seferde normalize et — train ve test ortak eksende olmalı
    combined["t"] = (combined["t_abs"] - combined["t_abs"].min()).astype("int16")
    combined = combined.drop(columns=["t_abs"])

    if combined.duplicated(["cell", "t"]).any():
        n_dup = int(combined.duplicated(["cell", "t"]).sum())
        raise ValueError(
            f"(hücre, ay) çifti {n_dup} kez tekrarlıyor. Lag ve komşuluk "
            f"özellikleri benzersiz grid varsayıyor — veri yapısını kontrol et."
        )

    train = combined[~combined["is_test"]].reset_index(drop=True)
    test = combined[combined["is_test"]].reset_index(drop=True)
    return train, test


def report(df: pd.DataFrame, name: str) -> None:
    cols = C.COLUMNS
    mem = df.memory_usage(deep=True).sum() / 1e9
    print(
        f"[{name}] {len(df):,} satır × {df.shape[1]} kolon | {mem:.2f} GB | "
        f"hücre={df['cell'].nunique():,} | ay aralığı t=[{df['t'].min()}, {df['t'].max()}]"
    )
    if cols.target in df.columns:
        y = df[cols.target]
        print(f"        hedef: ort={y.mean():.4f} std={y.std():.4f} null={y.isna().mean():.2%}")
