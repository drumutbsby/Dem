#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_kalite_testi.py — "MTP kaliteden odun veriyor mu?" sorusunun
IDDIA degil OLCUM ile cevabi.

Mantik: sicaklik 0 (greedy) ile bir model DETERMINISTIKTIR — ayni girdi hep
ayni ciktiyi verir. Spekulatif kod cozme (MTP) matematiksel olarak kayipsizsa,
MTP acikken ve kapaliyken uretilen metin KARAKTER KARAKTER AYNI olmalidir.
Farkliysa implementasyon kayipli demektir ve bunu burada goruruz.

Kullanim:
  1) MTP'siz sunucu calisirken bir kez calistirin  -> referans kaydedilir
  2) MTP'ye gectikten sonra tekrar calistirin      -> otomatik karsilastirir
"""

import hashlib
import json
import os
import time
import urllib.request

PORT = int(os.environ.get("LLM_PORT", "8080"))
KOK_URL = "http://127.0.0.1:%d" % PORT
KAYIT = os.path.expanduser("~/llm_greedy_referans.json")

# Deterministik olmasi icin: temperature=0, sabit seed, dusunme kapali
SORULAR = [
    "Turkiye'nin en uzun nehri hangisidir? Tek cumleyle cevapla.",
    "Bir kredi portfoyunde beklenen kayip formulunu yaz ve terimleri acikla.",
    "Python'da bir listedeki tekrar eden elemanlari bulan kisa bir fonksiyon yaz.",
]


def sor(metin):
    govde = {
        "messages": [{"role": "user", "content": metin}],
        "max_tokens": 400,
        "temperature": 0.0,
        "top_k": 1,
        "seed": 1234,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = urllib.request.Request(KOK_URL + "/v1/chat/completions",
                               data=json.dumps(govde).encode(),
                               headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(r, timeout=1800) as y:
        cevap = json.loads(y.read().decode())
    sure = time.time() - t0
    icerik = cevap["choices"][0]["message"]["content"]
    uretilen = cevap.get("usage", {}).get("completion_tokens", 0)
    return icerik, uretilen, sure


print("=" * 66)
print("GREEDY (temperature=0) DETERMINIZM TESTI")
print("=" * 66)

sonuclar = []
toplam_token = 0.0
toplam_sure = 0.0
for i, s in enumerate(SORULAR, 1):
    print("\n[%d/%d] %s" % (i, len(SORULAR), s[:60]))
    metin, tok, sure = sor(s)
    ozet = hashlib.sha256(metin.encode()).hexdigest()[:16]
    sonuclar.append({"soru": s, "cevap": metin, "sha": ozet})
    toplam_token += tok
    toplam_sure += sure
    print("    sha256[:16] = %s | %d token | %.1f sn (%.2f tok/sn)"
          % (ozet, tok, sure, tok / sure if sure else 0))

hiz = toplam_token / toplam_sure if toplam_sure else 0
print("\nOrtalama hiz: %.2f token/sn" % hiz)

if os.path.exists(KAYIT):
    with open(KAYIT) as f:
        onceki = json.load(f)
    print("\n" + "=" * 66)
    print("KARSILASTIRMA (referans: %s)" % onceki.get("etiket", "?"))
    print("=" * 66)
    ayni = 0
    for eski, yeni in zip(onceki["sonuclar"], sonuclar):
        esit = eski["sha"] == yeni["sha"]
        ayni += 1 if esit else 0
        print("%-45s %s" % (yeni["soru"][:45],
                            "AYNI" if esit else "FARKLI"))
        if not esit:
            print("   eski: %s" % eski["cevap"][:120].replace("\n", " "))
            print("   yeni: %s" % yeni["cevap"][:120].replace("\n", " "))
    print("\n%d/%d cevap birebir ayni." % (ayni, len(sonuclar)))
    if ayni == len(sonuclar):
        print("-> SONUC: Hizlandirma KALITEDEN ODUN VERMIYOR (cikti ozdes).")
    else:
        print("-> SONUC: Ciktilar farkli. Spekulatif kod cozme bu surumde")
        print("   tam kayipsiz degil; kritik islerde kapatmayi degerlendirin.")
    print("\nHiz: %.2f -> %.2f token/sn (%.1fx)"
          % (onceki.get("hiz", 0), hiz,
             hiz / onceki["hiz"] if onceki.get("hiz") else 0))
else:
    etiket = os.environ.get("ETIKET", "MTP kapali (referans)")
    with open(KAYIT, "w") as f:
        json.dump({"etiket": etiket, "hiz": hiz, "sonuclar": sonuclar}, f)
    print("\nReferans kaydedildi: %s" % KAYIT)
    print("Simdi MTP'ye gecip bu betigi TEKRAR calistirin; otomatik karsilastirir.")
