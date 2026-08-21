# Yerel LLM Kurulumu — Güvenlik Değerlendirmesi (Test Ortamı Talebi)

*Hazırlanma tarihi: 21 Ağustos 2026 · Kapsam: test sunucusu · Talep eden: veri/risk analitiği*

Bu belge, banka sunucusunda çalıştırılacak yerel dil modeli servisi için güvenlik
ekibinin sorabileceği soruları önden cevaplamak üzere hazırlanmıştır. Riskler
olduğu gibi listelenmiştir; azaltıcı önlemler her maddenin yanında verilmiştir.

## 1. Ne kuruluyor

| | |
|---|---|
| Bileşen | `llama.cpp` — açık kaynak çıkarım motoru (MIT lisansı) |
| Model | Qwen3.5-122B-A10B, GGUF 4-bit kuantize (**Apache 2.0**, ticari kullanıma açık) |
| Çalışma şekli | Tek bir kullanıcı seviyesinde işlem (`llama-server`), yalnızca CPU |
| Kaynak ihtiyacı | ~72 GB RAM, ~80 GB disk, GPU gerekmez |

Model ağırlıkları Alibaba Cloud (Qwen ekibi) tarafından yayımlanmış, GGUF dönüşümü
Unsloth tarafından yapılmıştır. Her iki dağıtım da Apache 2.0'dır; kurumsal kullanımda
lisans kısıtı yoktur.

## 2. Veri akışı — veri nereye gidiyor

**Hiçbir yere.** Servis `127.0.0.1` (loopback) adresine bağlanır; sunucu dışından
erişilemez. Model dosyaları diskte durur, çıkarım tamamen bellekte yapılır. Ne istem
(prompt) ne de cevap herhangi bir dış servise gönderilir. İnternet bağlantısı yalnızca
kurulum sırasında model dosyalarını indirmek için gerekmiştir; çalışma anında hiçbir
ağ çıkışı yoktur.

```
Dataiku (aynı sunucu)  ──HTTP──>  127.0.0.1:8080  ──>  RAM'deki model
                                   (dışarı açık değil)
```

## 3. Riskler ve azaltıcı önlemler

| # | Risk | Değerlendirme | Azaltıcı önlem |
|---|---|---|---|
| 1 | **İstem günlükleri diske yazılıyor** | Gerçek risk. Kullanıcılar istemlere müşteri verisi yapıştırırsa bu içerik sunucu günlüğüne düşebilir | Günlük dosyasına dosya sistemi izniyle erişimi kısıtlayın, günlük döndürme (logrotate) ve saklama süresi tanımlayın; ayrıntılı günlükleme kapalı tutulsun |
| 2 | **Uç noktada kimlik doğrulama yok** | Sunucuda kabuk erişimi olan herkes modeli sorgulayabilir. Loopback olduğu için ağ üzerinden erişilemez | Test ortamında kabul edilebilir. Prod'da ters vekil (reverse proxy) + jeton doğrulaması eklenmeli |
| 3 | **Tedarik zinciri: model dosyaları** | Ağırlıklar üçüncü taraf (Unsloth) tarafından dönüştürülmüş, internetten indirilmiştir | İndirilen dosyaların SHA256 özetleri kayıt altına alındı (`MANIFEST.txt`); test sunucusuna taşımada aynı özetler doğrulanır |
| 4 | **Tedarik zinciri: llama.cpp** | Kaynak koddan derlendi; GGUF ayrıştırıcılarında geçmişte güvenlik açıkları bildirilmiştir | Kullanılan sürümün commit'i kayıt altındadır; güvenlik yamaları için periyodik güncelleme planlanmalı. Yalnızca kurum içinde üretilmiş model dosyaları yüklenmelidir |
| 5 | **Model çıktısı doğrulanmamıştır** | Model hata yapabilir, uydurabilir. Bankacılıkta karar mekanizmasına doğrudan bağlanması uygun değildir | Sistem mesajına "sayı/mevzuat uydurma" kuralı eklendi; çıktılar **insan onayına** tabi olmalı, otomatik karara bağlanmamalı |
| 6 | **Kaynak çekişmesi** | Servis üretim sırasında CPU'yu doyurur; aynı sunucudaki diğer işleri yavaşlatabilir | İş parçacığı sayısı sınırlandırılabilir (`-t`); test ortamında izole çalıştırılacak |
| 7 | **Kişisel veri işleme** | Kullanıcı istemine girilen veri modelin bağlamına girer, ancak sunucudan çıkmaz | Sistem mesajında müşteri bilgisinin gereksiz tekrarı yasaklandı; kullanıcı bilgilendirmesi yapılmalı |

## 4. Test ortamı için talep

- Ayrılmış bir test sunucusu (≥ 96 GB RAM, ≥ 100 GB disk, AVX2 destekli CPU)
- Kullanıcı seviyesinde işlem çalıştırma yetkisi (kök/root yetkisi **gerekmez**)
- Dataiku'da bir LLM Mesh bağlantısı (`http://127.0.0.1:8080/v1`)
- İnternet erişimi **gerekmez** — dosyalar taşınarak getirilecektir

## 5. Üretime geçiş için ön koşullar

Test aşaması başarılı olursa, prod talebinden önce aşağıdakiler tamamlanmalıdır:

1. Uç noktaya kimlik doğrulama eklenmesi (jeton veya ters vekil)
2. Günlük yönetimi: saklama süresi, erişim kısıtı, kişisel veri filtresi
3. llama.cpp sürüm sabitleme ve güvenlik güncelleme takvimi
4. Model çıktılarının insan onayı olmadan karara bağlanmayacağının yazılı teyidi
5. Kapasite planı: eş zamanlı kullanıcı sayısı ve yanıt süresi beklentisi
   (ölçülen: 6,85 token/sn, tek kullanıcı; 200 kelimelik cevap ≈ 45 saniye)
6. Model ve model çıktılarının banka model risk yönetimi envanterine kaydı

## 6. Ölçülmüş performans (kaynak sunucu)

| | |
|---|---|
| Donanım | Xeon Gold 6342, 32 vCPU, 127 GB RAM, GPU yok |
| Üretim hızı | 6,85 token/sn |
| Model yükleme | 66 saniye |
| Bellek kullanımı | ~72 GB (model) + ~3 GB (32K bağlam) |

Ayrıntılı kurulum ve ölçümler: `docs/dataiku-llm-kurulum.md`
