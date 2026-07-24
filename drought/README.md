# A Step Ahead of Drought — ITU / Zindi

GRACE uydu verisiyle bir ay sonrasının Toplam Su Depolamasını (TWS) tahmin eden pipeline.

## Kurulum

```bash
pip install -r requirements.txt
```

## Sıra

**1. Şemayı çıkar** (bende veri yok, kolon isimlerini doğrulamam gerekiyor):

```bash
python inspect_data.py "C:\Users\MSİ\Desktop\proje2"
```

Çıktıyı bana yapıştır. `src/config.py` içindeki `Columns` sınıfını gerçek
isimlerle güncelleyeceğiz. Bu adım atlanırsa `dataio.validate_schema`
yüksek sesle hata verir — sessizce yanlış çalışmaz.

**2. Veri yolunu ayarla:**

```bash
set DROUGHT_DATA_DIR=C:\Users\MSİ\Desktop\proje2   # Windows
export DROUGHT_DATA_DIR=/path/to/data              # Linux/Mac
```

**3. Eğit:**

```bash
python -m src.train
```

**4. Submission üret:**

```bash
python -m src.predict
```

## Tasarım kararları ve gerekçeleri

**Hedef = delta, seviye değil.** Model `TWS_{t+1} - TWS_t` öğreniyor, tahmin
aşamasında `TWS_t` geri ekleniyor (`config.PREDICT_DELTA`). Persistence sinyali
modelden çıkarıldığı için ağaçlar artık asıl zor kısma — değişimin yönü ve
büyüklüğüne — kapasite ayırıyor.

**Persistence baseline her fold'da raporlanıyor.** `TWS_{t+1} = TWS_t` bu
problemde güçlü bir taban çizgisi. Modelin ona göre kazancı görünmüyorsa
özellikler işe yaramıyor demektir; skorun mutlak değeri yanıltıcı olabilir.

**Zaman bazlı CV, rastgele KFold değil.** Rolling-origin bölme: her fold'da
train daima validation'dan önceki aylardan oluşuyor. Rastgele KFold aynı
hücrenin komşu aylarını iki tarafa dağıtıp lokal skoru şişirir ve private
leaderboard'da (test'in %70'i) çöker.

**Sızıntı kontrolü.** Hiçbir özellik t anından sonraki bilgiyi kullanmıyor.
Mevsimsel iklim ortalamaları bile hedeften değil, gözlenen `TWS_t` kolonundan
üretiliyor. Uzamsal komşuluk özellikleri komşu hücrelerin *t anındaki gözlenen*
değerlerinden geliyor — komşu hedeflerinden değil. Zindi kural metni veri
sızıntısını açıkça diskalifiye sebebi sayıyor.

**Determinizm.** `deterministic=True` + `force_row_wise=True` + sabit
`num_threads`. LightGBM varsayılan ayarlarla çok çekirdekli çalışırken
deterministik değildir ve Zindi, tekrar çalıştırmada skor kayarsa sıralamayı
düşürme hakkını saklı tutuyor.

Sentetik veriyle ölçüm (LightGBM 4.7.0):

| Karşılaştırma | Sonuç |
|---|---|
| Aynı ayar, iki ayrı koşu | OOF bit-bazında aynı, fark 0.0 |
| 8 thread vs 2 thread | OOF bit-bazında aynı, fark 0.0 |

Yani belirleyici olan iki flag; thread sayısı bu flag'ler açıkken sonucu
değiştirmiyor. `DROUGHT_NUM_THREADS=32` ile deneylerini hızlandırabilirsin —
ama teslim edilen kodda varsayılanı sabit bırak, hakem makinesinin çekirdek
sayısına bağımlılık yaratmamak ucuz bir sigorta.

**Bellek.** 2.15M satır float32'de ~2-3 GB. Pipeline 16 GB'ta dönecek şekilde
yazıldı — 251 GB RAM'in avantajı veriyi sığdırmak değil, paralel deney
koşturmak. Teslim edilen kod hakem makinesinde çalışmak zorunda.

## Çıktılar

`outputs/` altında:

| dosya | içerik |
|---|---|
| `cv_result.json` | fold bazında RMSE, persistence karşılaştırması, en iyi iterasyon |
| `oof.npy` | out-of-fold tahminler (ensemble ve hata analizi için) |
| `feature_importance.csv` | gain bazlı özellik önemi |
| `lgb_fold*.txt`, `lgb_full.txt` | modeller |
| `submission.csv` | Zindi'ye yüklenecek dosya |

`train.py` ayrıca enlem kuşağına göre RMSE dağılımı yazdırıyor — bu doğrudan
raporun "AI trustworthiness" bölümüne gidecek malzeme (skorun %30'u).

## Yarışma kısıtları — kodun uyduğu maddeler

- Sadece açık kaynak paketler (numpy/pandas/lightgbm/sklearn)
- AutoML yok (AutoGluon, H2O, FLAML, auto-sklearn kullanılmıyor)
- Seed sabit, tekrar çalıştırmada aynı sonuç
- Custom paket yok, kod kendi içinde çalışıyor
- Harici veri eklenirse **gecikmesi 1 aydan kısa olmalı** (operasyonel kullanım
  şartı). ERA5T / IMERG Late / SMAP L3 uygun; ERA5 final (~2-3 ay gecikme) değil.

## Submission bütçesi

Günde 5, toplam 200. 13 Eylül'e kadar her gün maksimum atarsan hak bitiyor —
günde 3-4 planla, son haftaya ~30 sakla. Sonunda private leaderboard için
2 submission seçiliyor: birini en iyi lokal CV'ye, diğerini en iyi public
skora ayır.
