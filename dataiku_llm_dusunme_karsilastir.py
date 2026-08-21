#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_dusunme_karsilastir.py — Dusunme modu kaliteyi ne kadar degistiriyor?

Ayni soruyu ayni sunucuya iki kez sorar:
  1) Dusunme KAPALI  (hizli)
  2) Dusunme ACIK    (model once akil yurutur)
Cevaplari, sureleri ve hesaplanan sayinin dogrulugunu yan yana raporlar.

Soru bilerek cok adimli secildi: aritmetik + mevzuat + metodoloji.
Dogru cevap: EL = 0.032 x 0.45 x 250.000.000 = 3.600.000 TL
Betik cevapta bu sayiyi ariyor -> ozanel bir dogruluk olcusu verir.

Sure: ~2-10 dakika (dusunme modu yuzlerce token uretir).
Canli ilerleme gosterir, o yuzden notebook'ta bekledigini gorursunuz.
"""

import json
import os
import re
import time
import urllib.request

PORT = int(os.environ.get("LLM_PORT", "8080"))
KOK_URL = "http://127.0.0.1:%d" % PORT

SISTEM_MESAJI = """Sen bir bankanin veri ve risk analitigi ekibine destek veren yapay zeka asistanisin.

DIL VE TERMINOLOJI
- Her zaman Turkce yanit ver. Yerlesik Turkce finans terminolojisini kullan,
  Ingilizce terimleri kelime kelime cevirme.
- Dogru karsiliklar: default = temerrut (asla "varsayilan"), exposure = risk tutari,
  PD = temerrut olasiligi, LGD = temerrut halinde kayip orani,
  EAD = temerrut anindaki risk tutari, provision = karsilik, collateral = teminat,
  impairment = deger dusuklugu, backtesting = geriye donuk test.

CEVAP BICIMI
- Dogrudan cevapla, girizgah yapma. Hesap yaptiysan islemi acik goster.

DOGRULUK
- Emin olmadigin sayisal deger, oran veya mevzuat maddesi UYDURMA.
- BDDK, Basel III, TFRS 9 gibi duzenlemelerde genel cerceveyi anlat,
  madde numarasi ve tarih uydurma.
- Varsayim yaptiysan varsayimi acikca belirt."""

SORU = """Bir tuketici kredisi portfoyunde 12 aylik PD %3,2, LGD %45 ve toplam EAD
250 milyon TL olarak olculmustur.
(a) 12 aylik beklenen kaybi hesapla, islemi goster.
(b) Bu portfoy TFRS 9 kapsaminda Asama 1'den Asama 2'ye gecerse karsilik
    hesaplamasi nasil degisir?
(c) Geriye donuk testte gerceklesen temerrut orani %4,8 cikarsa hangi adimlari
    izlersin?"""

# Uretici onerisi: her mod icin farkli ornekleme parametreleri
# max_token: dusunmesiz modda butun butce cevaba gider; dusunme modunda
# butce once akil yurutmeye harcanir, o yuzden daha yuksek verilir.
# (Ilk olcumde dusunmesiz mod 800 token'da kesilmisti -> karsilastirma adaletsizdi.)
AYARLAR = [
    ("DUSUNME KAPALI", False, {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5}, 2500),
    ("DUSUNME ACIK", True, {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 1.5}, 5000),
]


def akisli_sor(dusunme, ornekleme, max_token):
    """Streaming istek: bekleme sirasinda canli ilerleme gosterir."""
    govde = {
        "messages": [{"role": "system", "content": SISTEM_MESAJI},
                     {"role": "user", "content": SORU}],
        "max_tokens": max_token,
        "chat_template_kwargs": {"enable_thinking": dusunme},
        "stream": True,
    }
    govde.update(ornekleme)
    r = urllib.request.Request(KOK_URL + "/v1/chat/completions",
                               data=json.dumps(govde).encode(),
                               headers={"Content-Type": "application/json"})
    cevap, dusunce, sayac = [], [], 0
    bitis_nedeni = None
    ilk_token_suresi = None
    t0 = time.time()
    with urllib.request.urlopen(r, timeout=3600) as y:
        for ham in y:
            satir = ham.decode("utf-8", "replace").strip()
            if not satir.startswith("data:"):
                continue
            veri = satir[5:].strip()
            if veri == "[DONE]":
                break
            try:
                parca = json.loads(veri)
            except ValueError:
                continue
            secim = parca.get("choices", [{}])[0]
            if secim.get("finish_reason"):
                bitis_nedeni = secim["finish_reason"]
            delta = secim.get("delta", {})
            if delta.get("reasoning_content"):
                dusunce.append(delta["reasoning_content"])
                sayac += 1
            if delta.get("content"):
                cevap.append(delta["content"])
                sayac += 1
            if ilk_token_suresi is None and sayac:
                ilk_token_suresi = time.time() - t0
            if sayac % 50 == 0 and sayac:
                asama = "dusunuyor" if (dusunce and not cevap) else "yaziyor  "
                print("   %s... %4d token | %3.0f sn" % (asama, sayac, time.time() - t0),
                      end="\r", flush=True)
    sure = time.time() - t0
    print("\r" + " " * 62)  # ilerleme satirini temizle
    return "".join(cevap), "".join(dusunce), sayac, sure, ilk_token_suresi, bitis_nedeni


def dogru_sayi_var_mi(metin):
    """EL = 3.600.000 TL sayisi cevapta geciyor mu?"""
    sade = re.sub(r"[ .,]", "", metin)
    return ("3600000" in sade) or ("36milyon" in sade.lower()) or ("36mntl" in sade.lower())


def main():
    try:
        urllib.request.urlopen(KOK_URL + "/health", timeout=5)
    except Exception:
        print("HATA: sunucu %s adresinde yanit vermiyor." % KOK_URL)
        print("Once dataiku_llm_baslat.py betigini calistirin.")
        return

    print("=" * 70)
    print("DUSUNME MODU KALITE KARSILASTIRMASI")
    print("=" * 70)
    print(SORU)
    print("\nDogru beklenen kayip: 0,032 x 0,45 x 250.000.000 = 3.600.000 TL")

    sonuclar = []
    for ad, dusunme, ornekleme, max_token in AYARLAR:
        print("\n" + "=" * 70)
        print(ad)
        print("=" * 70)
        try:
            cevap, dusunce, token, sure, ilk, bitis = akisli_sor(
                dusunme, ornekleme, max_token)
        except Exception as e:
            print("HATA: %s" % e)
            continue
        if dusunce:
            print("--- Dusunme zinciri (ilk 500 karakter, toplam %d karakter) ---"
                  % len(dusunce))
            print(dusunce.strip()[:500] + "...")
            print()
        print("--- CEVAP ---")
        print(cevap.strip())
        if bitis == "length":
            print("\n!!! UYARI: cevap token limitine (%d) takilip KESILDI." % max_token)
            print("    Karsilastirma adaletsiz olabilir; limiti artirip tekrarlayin.")
        dogru = dogru_sayi_var_mi(cevap)
        print("\nSure: %.0f sn | Token: %d | Ilk token: %.1f sn | Hiz: %.2f tok/sn"
              % (sure, token, ilk or 0, token / sure if sure else 0))
        print("Beklenen kayip dogru mu (3.600.000 TL): %s" % ("EVET" if dogru else "HAYIR/bulunamadi"))
        sonuclar.append((ad, sure, token, dogru, len(dusunce)))

    if len(sonuclar) == 2:
        print("\n" + "=" * 70)
        print("OZET")
        print("=" * 70)
        print("%-16s %8s %8s %10s %12s" % ("Mod", "Sure", "Token", "Hesap", "Dusunme"))
        for ad, sure, token, dogru, dus in sonuclar:
            print("%-16s %6.0fsn %8d %10s %10d kr"
                  % (ad, sure, token, "dogru" if dogru else "hatali", dus))
        yavaslama = sonuclar[1][1] / sonuclar[0][1] if sonuclar[0][1] else 0
        print("\nDusunme modu %.1fx daha uzun surdu." % yavaslama)
        print("Cevaplari yukaridan okuyup icerik kalitesini kendiniz karsilastirin:")
        print("  - (b) ve (c) siklarinda derinlik farki var mi?")
        print("  - Terminoloji dogru mu (temerrut/karsilik/risk tutari)?")
        print("  - Uydurma mevzuat maddesi veya sayi var mi?")


main()
