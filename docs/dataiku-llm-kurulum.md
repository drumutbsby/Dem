# Qwen3.5-122B-A10B — Dataiku Sunucusunda CPU Kurulumu

*Kurulum ve ölçümler: 21 Ağustos 2026. Tüm rakamlar bu sunucuda gerçekten ölçüldü.*

## Sunucu

| | |
|---|---|
| İşletim sistemi | RHEL 9.8 (kernel 5.14.0-687), glibc 2.34 |
| CPU | Intel Xeon Gold 6342 @ 2.80 GHz, 32 mantıksal çekirdek (VMware) |
| RAM | 127,1 GB (kurulum sırasında ~115 GB boş) |
| Disk | 3,8 TB boş (`/data/dataiku/DATA_DIR`) |
| GPU | Yok (VMware SVGA) |

## Model

- **Qwen3.5-122B-A10B**, `unsloth/Qwen3.5-122B-A10B-GGUF`, **UD-Q4_K_XL** (3 parça, 71,73 GiB)
- 122B toplam / ~10B aktif parametre (MoE, 256 uzmandan 8'i seçiliyor), 48 katman
- Managed folder: `/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ` (Dataiku'da `VERI`)
- Bu makineye sığan en büyük Qwen: 235B Q4 (134 GB) RAM'e sığmıyor, 2.4T ise 397 GB'den başlıyor.

## llama.cpp

glibc 2.34 olduğu için hazır `ubuntu-x64` binary'leri (glibc ≥ 2.35 ister) **çalışmaz**; kaynaktan derlendi:

```bash
git clone --depth 1 https://github.com/ggml-org/llama.cpp ~/llama.cpp
cd ~/llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
cmake --build build --config Release -j 32 --target llama-server llama-cli llama-bench
```

`LLAMA_CURL=OFF` çünkü RHEL'de `libcurl-devel` yok ve model dosyaları zaten yerel.
`GGML_NATIVE=ON` AVX-512'yi etkinleştirir.

## Ölçüm sonuçları

### Thread taraması (llama-bench, 71,73 GiB model)

| Thread | Üretim (tok/sn) | Prefill (tok/sn) |
|---:|---:|---:|
| 16 | 5,37 | 48,7 |
| 20 | 5,89 | 56,8 |
| 24 | 6,25 | 63,4 |
| 28 | 6,75 | **73,0** |
| 32 | **7,23** | 66,4 |

İki farklı optimum: **üretim 32**, **prefill 28** thread. 32 thread'te prefill düşüyor
çünkü tüm vCPU'lar dolduğunda işletim sistemi/Dataiku ile çekişme başlıyor
(sapma da ±5,42'ye çıkıyor). Çözüm: `-t 32 -tb 28`.

### Denenip elenen: MTP spekülatif kod çözme

| Yapılandırma | Hız |
|---|---|
| Q4_K_XL, `-t 24` | 5,80 tok/sn |
| MTP + `--spec-type draft-mtp --spec-draft-n-max 6`, `-t 24` | **3,63 tok/sn (0,63×)** |

Üretici ~1,5–2× hızlanma bildiriyor ama bu **GPU için geçerli**. CPU + MoE'de ters teper:
(1) 6 token'ı paralel doğrulamak 6 kat hesap ister ve CPU'da bu süre gizlenemez;
(2) MoE'de her token farklı uzmanları tetiklediğinden toplu doğrulama, "ağırlıkları bir kez
okuruz" avantajını yok eder. Ayrıca yükleme 66 → 125 sn'ye çıkar. **Kullanmayın.**

### Denenip elenen: NUMA

`--numa distribute` → 7,22 tok/sn (değişim yok). Sanal makine tek NUMA düğümü olarak
sunuluyor ya da hipervizör zaten serpiştiriyor. Bırakın kapalı kalsın.

### Özet kazanç

5,80 → **7,23 tok/sn (1,25×)**, tek kaynak: doğru thread sayısı. Model yükleme ~66 sn.
Efektif bellek bandı ~40 GB/s (teorik ~200 GB/s); tavana ulaşılamamasının sebebi
sanallaştırma katmanı, daha fazla ayarla kapatılamadı.


### Sistem mesajının etkisi (ölçüldü)

Sistem mesajı olmadan model İngilizce terimleri kelimesi kelimesine çeviriyordu:
"PD (Olasılık Varsayılan)", "Varsayılan anında". Terim sözlüğü içeren sistem mesajı
eklendikten sonra aynı soruda çıktı: **"PD (Temerrüt Olasılığı)", "LGD (Temerrüt Halinde
Kayıp Oranı)", "EAD (Temerrüt Anındaki Risk Tutarı)"** — hepsi doğru. Sistem mesajı
`dataiku_llm_baslat.py` içinde gömülü; Dataiku LLM Mesh'te de aynısını kullanın.
Maliyeti 533 girdi token'ı (yaklaşık 3 saniye prefill).

### Düşünme modu: 2,6× maliyet, kalitede net kazanç yok (adil test)

Çok adımlı bir soruyla (aritmetik + TFRS 9 aşama geçişi + geriye dönük test metodolojisi),
her iki moda da yeterli token bütçesi verilerek ölçüldü:

| | Düşünme kapalı | Düşünme açık |
|---|---|---|
| Süre | 147 sn | **389 sn (2,6×)** |
| Üretilen token | 991 | 2.683 (+5.109 karakter akıl yürütme) |
| Beklenen kayıp (3.600.000 TL) | doğru | doğru |
| Hız | 6,72 tok/sn | 6,90 tok/sn |

**Düşünme modunun kazandırdığı:** (c) şıkkında 6 adım (5 yerine), Gini ve Hosmer-Lemeshow
gibi somut test adları, segment bazlı sapma analizi; (b) şıkkında faiz gelirinin brüt
tanınmaya devam ettiği doğru detayı.

**Düşünme modunun kaybettirdiği:**
- **Notasyon hatası:** yüzdeleri "%3,2 (%0,032)" diye yazdı — 0,032 zaten %3,2'dir,
  "%0,032" yanlıştır. Düşünmesiz mod bunu doğru yazmıştı ("%3,2 = 0,032").
- (b) şıkkında anlamsız bir madde: "risk iştirak göstergeleri değişir" (böyle bir terim yok).
- Daha fazla dil kayması: "Zaman Horizonu" (doğrusu zaman ufku), "yüksek çıkarırsa".

**Düşünmesiz modun öne çıktığı yer:** sapmanın istatistiksel olarak anlamlı olup olmadığını
sorgulayan madde — gerçek bir model validasyon uzmanının ilk soracağı şey. Düşünme modunda
bu yok.

**Karar: düşünme modu kapalı kalsın.** 2,6× süre karşılığında aldığınız birkaç ek madde,
getirdiği notasyon ve dil hatalarını telafi etmiyor. Düşünme modu kullanılacaksa
`temperature=0.7` ile denenmeli (üretici 1.0 öneriyor ama Q4 ile gürültü artıyor).

Akıl yürütme zinciri Türkçe soruya rağmen **İngilizce** üretiliyor; Qwen'de normaldir,
cevabın dilini etkilemez.

### LaTeX uyarısı

Model matematiği varsayılan olarak LaTeX ile yazıyor (`$EL = PD \times LGD$`). Dataiku
Prompt Studio ve Agent Chat bunu render etmez, ham `$` ve `\times` görünür. Sistem mesajına
"matematiği düz metin yaz, LaTeX kullanma" satırı eklendi.

### -tb (prefill thread) kazancı

Uçtan uca gerçek istek hızı: 5,80 → 6,50 (`-t 32`) → **6,85 tok/sn** (`-t 32 -tb 28`).
llama-bench'in saf üretim ölçümü 7,23 tok/sn; aradaki fark girdi işleme, sohbet şablonu
ve HTTP yükünden geliyor, beklenen bir fark.

## Üretim yapılandırması

```bash
~/llama.cpp/build/bin/llama-server \
  -m /data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ/Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf \
  -c 32768 -t 32 -tb 28 --host 127.0.0.1 --port 8080 --jinja
```

Yalnızca `-00001` parçası verilir; diğerlerini otomatik bulur. Bellek: ~72 GiB ağırlık +
32K bağlam için ~3 GiB KV cache. Bağlam 131072'ye çıkarılabilir (~12 GiB KV).

**Dataiku ile birlikte yaşam:** `-t 32` üretim sırasında tüm vCPU'ları doldurur. Sunucuda
eş zamanlı ağır Dataiku işleri koşuyorsa `-t 28` tercih edin — 6,75 tok/sn (tepe hızın %93'ü)
verir ve 4 vCPU boşta kalır.

## Dataiku LLM Mesh bağlantısı

Administration → Connections → New connection → **LLM Mesh → OpenAI (compatible)**

| Alan | Değer |
|---|---|
| Base URL | `http://127.0.0.1:8080/v1` |
| API key | herhangi bir metin (örn. `local`) — llama.cpp doğrulama yapmaz |
| Model adı | serbest (örn. `qwen3.5-122b`) |

## Kullanım notları

- **Düşünme modunu kapalı tutun** (ölçüm yukarıda): 2,8× maliyet getiriyor, bu iş yükünde
  kalite kazancı görülmedi. İstek gövdesine:
  `"chat_template_kwargs": {"enable_thinking": false}`
  Çok adımlı araştırma/analiz görevlerinde tekrar denemeye değer.
- **Örnekleme (üretici önerisi):** düşünme modunda `temperature=1.0, top_p=0.95, top_k=20,
  presence_penalty=1.5`; instruct modunda `temperature=0.7, top_p=0.8, top_k=20,
  presence_penalty=1.5`.
- **Türkçe terminoloji:** model İngilizce finans terimlerini kelimesi kelimesine çeviriyor
  ("default" → "varsayılan", olması gereken "temerrüt"). Sistem mesajına terim sözlüğü
  ekleyin: *"Türkçe finans terminolojisi kullan: default=temerrüt, exposure=risk tutarı,
  recovery=tahsilat. İngilizce terimleri kelime kelime çevirme."*
- **Eş zamanlılık:** tek istek varsayımıyla ayarlandı. Çok kullanıcı için `-np` ile paralel
  slot açılabilir ama her slot kendi KV cache'ini ister ve hız kullanıcı başına düşer.

## Depodaki betikler

| Dosya | İşlevi |
|---|---|
| `sistem_kontrol.py` | Herhangi bir makinede hangi model sürümünün çalışacağını raporlar |
| `dataiku_llm_kontrol.py` | Ön kontrol: klasör yolu, dosya bütünlüğü, glibc, araçlar, RAM |
| `dataiku_llm_kur.py` | llama.cpp'yi kaynaktan derler |
| `dataiku_llm_baslat.py` | Sunucuyu başlatır, deneme sorusu sorar, hız ölçer |
| `dataiku_llm_hiz_ayari.py` | Thread/NUMA taraması yapıp en iyi ayarla yeniden başlatır |
| `dataiku_llm_kalite_testi.py` | Greedy determinizm testi: hızlandırma çıktıyı değiştiriyor mu |
| `dataiku_llm_mtp_yukselt.py` | MTP sürümü (bu donanımda faydasız, GPU eklenirse kullanılabilir) |
| `dataiku_llm_dusunme_karsilastir.py` | Düşünme modunu açık/kapalı karşılaştırır, hesabı doğrular |
