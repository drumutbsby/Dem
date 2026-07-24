"""Tek ayar noktası.

inspect_data.py çıktısı geldikten sonra sadece COLUMNS bloğu güncellenecek;
pipeline'ın geri kalanı bu isimleri kullanır.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------
# Yollar — kendi makinene göre DATA_DIR'i değiştir
# --------------------------------------------------------------------------
DATA_DIR = Path(os.environ.get("DROUGHT_DATA_DIR", r"C:\Users\MSİ\Desktop\proje2"))
OUT_DIR = Path(os.environ.get("DROUGHT_OUT_DIR", "outputs"))

TRAIN_FILE = "Train.csv"
TEST_FILE = "Test.csv"
SUBMISSION_TEMPLATE = "SampleSubmission.csv"

# --------------------------------------------------------------------------
# Determinizm — Zindi kod incelemesi bunu şart koşuyor.
# NUM_THREADS'i SABİT tut. os.cpu_count() kullanma: hakem farklı çekirdek
# sayısında çalıştırınca LightGBM farklı sonuç üretir ve sıralaman düşürülebilir.
# --------------------------------------------------------------------------
SEED = 42

# Deneyler sırasında DROUGHT_NUM_THREADS=32 ile hızlanabilirsin, ama teslim
# edilen kodda varsayılan sabit kalmalı: farklı thread sayısı farklı sonuç
# üretiyor (aşağıdaki nota bak), hakem makinesi 40 çekirdekli olmayacak.
NUM_THREADS = int(os.environ.get("DROUGHT_NUM_THREADS", "8"))


@dataclass(frozen=True)
class Columns:
    """Veri setindeki kolon isimleri. inspect_data.py çıktısına göre doğrula."""

    # Kimlik / koordinat
    id: str = "ID"
    lat: str = "lat"
    lon: str = "lon"
    date: str = "date"

    # Hedef: bir sonraki ayın Toplam Su Depolaması (TWS)
    target: str = "target"

    # t anındaki gözlenen TWS — persistence baseline'ının temeli
    tws_current: str = "TWS_t"

    # Çoklu ölçek SPEI kuraklık indeksleri
    spei: tuple[str, ...] = tuple(f"SPEI_{i}" for i in range(1, 13))

    # Toprak nemi ve diğer kovaryatlar
    extra_numeric: tuple[str, ...] = ("soil_moisture",)

    @property
    def raw_features(self) -> list[str]:
        return [self.tws_current, *self.spei, *self.extra_numeric]


COLUMNS = Columns()

# --------------------------------------------------------------------------
# Özellik mühendisliği
# --------------------------------------------------------------------------
LAGS: tuple[int, ...] = (1, 2, 3, 6, 12)
ROLL_WINDOWS: tuple[int, ...] = (3, 6, 12)

# Uzamsal komşuluk: grid adımının kaç katına kadar komşu toplanacak
SPATIAL_RING: int = 1

# --------------------------------------------------------------------------
# Doğrulama (CV) — zaman bazlı. Rastgele KFold KULLANMA.
# --------------------------------------------------------------------------
N_FOLDS = 4
VAL_MONTHS_PER_FOLD = 1  # her fold'da kaç ay holdout
GAP_MONTHS = 0  # hedef t+1 olduğu için train/val arasına boşluk gerekmiyor

# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
LGB_PARAMS: dict = {
    "objective": "regression",
    "metric": "rmse",
    "learning_rate": 0.03,
    "num_leaves": 255,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "max_bin": 255,
    "verbosity": -1,
    # --- determinizm bloğu: bu üçü birlikte gerekli ---
    "seed": SEED,
    "deterministic": True,
    "force_row_wise": True,
    "num_threads": NUM_THREADS,
}

NUM_BOOST_ROUND = 20_000
EARLY_STOPPING_ROUNDS = 200

# --------------------------------------------------------------------------
# Hedef dönüşümü
# Delta (TWS_{t+1} - TWS_t) tahmin etmek, seviye tahmininden neredeyse her
# zaman daha iyi: persistence sinyali modelden çıkarılıp artık öğrenilir.
# --------------------------------------------------------------------------
PREDICT_DELTA = True
