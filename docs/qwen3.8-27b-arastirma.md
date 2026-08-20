# Qwen3.8-27B — Hugging Face Araştırması ve İndirme Bulguları

*Araştırma tarihi: 20 Ağustos 2026 · Kaynak: Hugging Face API ve resmi model kartı*

## 1. Model Kimliği

| Alan | Değer |
|---|---|
| Depo | [`Qwen/Qwen3.8-27B`](https://huggingface.co/Qwen/Qwen3.8-27B) |
| Yayın tarihi | 5 Ağustos 2026 |
| Parametre sayısı | 27,78 milyar (yoğun/dense, BF16) |
| Mimari | `Qwen3_5ForConditionalGeneration` (Qwen3.5 mimari temeli, `qwen3_5`) |
| Tür | Doğal (native) görüntü + video anlayan vizyon-dil modeli (image-text-to-text) |
| Bağlam uzunluğu | 262.144 token natif; YaRN ile 1.000.000 token'a genişletilebilir |
| Katman/boyut | 64 katman, hidden 5120, 24 attention head, 248.320 sözcük dağarcığı |
| Lisans | **Apache 2.0** (ticari kullanım serbest) |
| Erişim | **Gated değil** — giriş/onay gerektirmeden indirilebilir |
| Popülerlik | ~1,0 milyon indirme, 11.529 beğeni (ana depo); unsloth GGUF tek başına 4,3 milyon indirme |

Öne çıkan özellikler (model kartından):
- **Düşünme modu varsayılan açık**; istek bazında kapatılabilir. `reasoning_effort` ile derinlik ayarı: `low` / `medium` / `xhigh` (varsayılan).
- **MTP (Multi-Token Prediction)** ile eğitilmiş — spekülatif kod çözmeyle (speculative decoding) hız kazancı.
- `preserve_thinking` ile geçmiş mesajlardaki akıl yürütme bağlamı korunuyor.
- Kodlama ve ajan görevlerinde güçlü: Terminal Bench 2.1: **73,0**, SWE-bench Pro: **61,7**, GPQA Diamond: **89,2**, IFBench: **79,5** (bir önceki Qwen3.6-27B'ye göre belirgin sıçrama).

## 2. Resmi ve Topluluk Varyantları

| Depo | Format | Boyut | Not |
|---|---|---|---|
| `Qwen/Qwen3.8-27B` | safetensors BF16 | **~55,6 GB** (18 parça) | Ana model |
| `Qwen/Qwen3.8-27B-FP8` | safetensors FP8 | **~30,9 GB** | vLLM/SGLang için resmi FP8 |
| `ggml-org/Qwen3.8-27B-GGUF` | GGUF | Q4_K_M 19 GB · Q8_0 29 GB · BF16 54 GB | Resmi GGUF; ayrıca `mmproj` (vizyon, ~1 GB) ve `mtp-*` taslak modeli (spekülatif decoding) içerir |
| `unsloth/Qwen3.8-27B-GGUF` | GGUF (imatrix) | IQ1_S 6 GB → Q8_K_XL 31 GB | En çok indirilen quant seti (4,3M indirme) |
| `lmstudio-community/Qwen3.8-27B-GGUF` / `-MLX-4bit` / `-MLX-8bit` | GGUF / MLX | ~16–30 GB | LM Studio ve Apple Silicon için |
| `bartowski/Qwen3.8-27B-GGUF` | GGUF | çeşitli | Alternatif quantlar |
| `unsloth/Qwen3.8-27B-NVFP4` | NVFP4 | ~15 GB | Blackwell GPU'lar için |

Aynı ailede dev amiral gemisi de yayınlandı: `Qwen/Qwen3.8-2.4T-A95B` (2,4 trilyon toplam / 95B aktif MoE) — 27B bunun kompakt, tek-GPU dostu kardeşi.

> ⚠️ "Uncensored/abliterated" etiketli türevler (orcarouter, JonathanColetti vb.) **resmi değildir**; üçüncü taraf modifikasyonlardır.

## 3. İndirme Yöntemleri

### a) Hugging Face CLI (önerilen)
```bash
pip install -U "huggingface_hub[cli]" hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1   # yüksek hızlı indirme

# Tam model (BF16, ~56 GB disk gerekir)
hf download Qwen/Qwen3.8-27B --local-dir ./Qwen3.8-27B

# FP8 varyantı (~31 GB)
hf download Qwen/Qwen3.8-27B-FP8 --local-dir ./Qwen3.8-27B-FP8

# GGUF'tan yalnızca tek bir quant çekmek (örn. Q4_K_M ~16 GB)
hf download unsloth/Qwen3.8-27B-GGUF --include "*UD-Q4_K_M*" --local-dir ./gguf
# Vizyon için mmproj dosyasını da ekleyin:
hf download ggml-org/Qwen3.8-27B-GGUF --include "mmproj-*Q8_0*" --local-dir ./gguf
```
İndirme kesintiye uğrarsa aynı komut kaldığı yerden devam eder (resume destekli); dosya bütünlüğü otomatik doğrulanır. Giriş (token) gerekmez çünkü model gated değil.

### b) Python (`snapshot_download`)
```python
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3.8-27B", local_dir="Qwen3.8-27B")
```

### c) Ollama (en pratik yerel kullanım)
```bash
ollama run qwen3.8        # varsayılan 27b, ~18 GB (4-bit)
ollama run qwen3.8:27b
```
MLX varyantları da mevcut: `qwen3.8:27b-mlx` (~18 GB), `qwen3.8:27b-mlx-bf16` (~56 GB).

### d) LM Studio
Uygulama içi aramada "Qwen3.8-27B" — `lmstudio-community` GGUF (PC) veya MLX (Mac) sürümünü tek tıkla indirir.

### e) Git LFS (önerilmez)
```bash
git lfs install
git clone https://huggingface.co/Qwen/Qwen3.8-27B
```
`.git` deposu nedeniyle ~2 kat disk tüketir; CLI tercih edin.

## 4. Donanım Gereksinimleri (yaklaşık)

| Format | İndirme boyutu | Asgari donanım |
|---|---|---|
| BF16 (tam) | ~56 GB | 80 GB GPU (A100/H100) veya 2×48 GB |
| FP8 (resmi) | ~31 GB | 40–48 GB GPU (L40S, A6000, RTX 6000 Ada) |
| GGUF Q8_0 | ~29 GB | 48 GB GPU veya 48 GB+ birleşik bellekli Mac |
| GGUF Q4_K_M | ~16–19 GB | **24 GB GPU (RTX 3090/4090)** veya 32 GB RAM'li Mac/PC |
| GGUF IQ3/Q2 | ~10–13 GB | 16 GB GPU (kalite kaybıyla) |
| GGUF IQ1/IQ2 | ~6–8 GB | 12 GB GPU (belirgin kalite kaybı) |

Uzun bağlam kullanılacaksa KV cache için ek bellek payı bırakın. llama.cpp'de görüntü/video girişi için `mmproj` dosyası, MTP hızlandırması için `mtp-*` taslak GGUF'u ayrıca yüklenmelidir.

## 5. Sunum (Serving) ve Önerilen Ayarlar

Resmi öneri: üretim için **SGLang**, **vLLM** veya TokenSpeed'in güncel sürümleri.

```bash
# vLLM örneği (FP8, 262K bağlam)
vllm serve Qwen/Qwen3.8-27B-FP8 --max-model-len 262144

# 1M bağlam için YaRN (model kartındaki resmi komut)
VLLM_ALLOW_LONG_MAX_MODEL_LEN=1 vllm serve Qwen/Qwen3.8-27B \
  --hf-overrides '{"text_config": {"rope_parameters": {"mrope_interleaved": true, "mrope_section": [11, 11, 10], "rope_type": "yarn", "rope_theta": 10000000, "partial_rotary_factor": 0.25, "factor": 4.0, "original_max_position_embeddings": 262144}}}' \
  --max-model-len 1000000
```

Önerilen örnekleme parametreleri (model kartı):
- **Düşünme modu:** `temperature=1.0, top_p=0.95, top_k=20, min_p=0.0, presence_penalty=0.0`
- **Instruct (düşünmesiz) mod:** `temperature=0.7, top_p=0.80, top_k=20, min_p=0.0, presence_penalty=1.5`
- Ajan görevlerinde çıktı payı: akıl yürütme için 262.144, nihai yanıt için 131.072 token önerisi.

## 6. Özet Değerlendirme

- Model **gerçek ve güncel**: Qwen3.8-27B, Qwen3.5 mimarisi üzerine inşa edilmiş, 5 Ağustos 2026'da çıkmış kompakt bir vizyon-dil modelidir; HF'de iki hafta içinde 1M+ indirme almıştır.
- **İndirme engeli yok**: Apache 2.0, gated değil, token gerektirmez.
- **En kolay yol**: `ollama run qwen3.8` (~18 GB). **En esnek yol**: `hf download` ile ihtiyaca uygun format (BF16 56 GB / FP8 31 GB / GGUF 6–31 GB).
- 24 GB'lık tüketici GPU'sunda Q4_K_M quant ile rahatça, 16 GB'ta IQ3 sınıfı quantlarla çalıştırılabilir.
- Hosted sürüm (1M bağlam, yerleşik araçlar) Qwen Cloud üzerinden "yakında" duyurulmuş durumda.
