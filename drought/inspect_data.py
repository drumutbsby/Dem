"""Şema çıkarma scripti — ÖNCE BUNU ÇALIŞTIR.

Kullanım (Windows, proje klasöründe):
    python inspect_data.py "C:\\Users\\MSİ\\Desktop\\proje2"

Çıktının tamamını kopyalayıp yapıştır. Hiçbir veri satırı yazdırmaz,
sadece kolon isimleri / tipler / özet istatistik üretir.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

MAX_PREVIEW_COLS = 60


def describe_csv(path: Path) -> None:
    print(f"\n{'=' * 70}")
    print(f"DOSYA: {path.name}  ({path.stat().st_size / 1e6:.1f} MB)")
    print("=" * 70)

    # Kolon adlarını ve tipleri küçük bir örnekten çıkar (tam dosyayı okumaya gerek yok)
    head = pd.read_csv(path, nrows=20_000)
    print(f"kolon sayısı: {head.shape[1]}")
    print("\n--- KOLONLAR (ad | dtype | örnek değer | ilk 20k'da null %) ---")
    for col in head.columns[:MAX_PREVIEW_COLS]:
        sample = head[col].dropna()
        example = repr(sample.iloc[0]) if len(sample) else "<hepsi null>"
        null_pct = head[col].isna().mean() * 100
        print(f"{col:<28} | {str(head[col].dtype):<10} | {example:<24} | {null_pct:5.1f}%")
    if head.shape[1] > MAX_PREVIEW_COLS:
        print(f"... ve {head.shape[1] - MAX_PREVIEW_COLS} kolon daha")

    # Satır sayısı (bellek yakmadan)
    with path.open("r", encoding="utf-8", errors="ignore") as fh:
        n_rows = sum(1 for _ in fh) - 1
    print(f"\ntoplam satır: {n_rows:,}")

    # Tarih / koordinat kolonlarını tespit et ve aralıklarını ver
    lowered = {c.lower(): c for c in head.columns}
    for key in ("date", "time", "lat", "latitude", "lon", "longitude"):
        if key in lowered:
            col = lowered[key]
            vals = pd.read_csv(path, usecols=[col]).iloc[:, 0]
            uniq = vals.nunique()
            print(f"{col}: min={vals.min()} max={vals.max()} benzersiz={uniq:,}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    root = Path(sys.argv[1])
    if not root.exists():
        print(f"HATA: klasör bulunamadı: {root}")
        sys.exit(1)

    print(f"KLASÖR: {root}\n")
    print("--- TÜM DOSYALAR ---")
    for p in sorted(root.rglob("*")):
        if p.is_file():
            print(f"{p.relative_to(root)}  ({p.stat().st_size / 1e6:.1f} MB)")

    for p in sorted(root.rglob("*.csv")):
        try:
            describe_csv(p)
        except Exception as exc:  # noqa: BLE001 - teşhis scripti, her hatayı göster
            print(f"\n{p.name} okunamadı: {exc}")


if __name__ == "__main__":
    main()
