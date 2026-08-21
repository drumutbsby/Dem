#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_mtp_yukselt.py — OPSIYONEL: MTP ile 1.5-2x hizlandirma.

Qwen3.5'in MTP (Multi-Token Prediction) katmanlarini iceren GGUF surumu,
llama.cpp'nin spekulatif kod cozme ozelligiyle uretimi ~1.5-2x hizlandirir.
(MTP destegi llama.cpp'ye 16 Mayis 2026'da girdi; bugun derlediginiz surumde var.)

Yaptiklari:
  1) MTP surumunu sunucuya indirir (73 GiB, kesintide kaldigi yerden devam eder)
  2) Calisan sunucuyu durdurup MTP + spekulatif decode ile yeniden baslatir
  3) Ayni deneme sorusunu sorup ESKI hizla karsilastirir

Not: MTP ile es zamanli istek (-np > 1) desteklenmiyor. Cok kullanicili
Dataiku senaryosunda MTP'yi kapatmak gerekebilir.
"""

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
MTP_DIZIN = os.path.join(KLASOR, "MTP")
BINARY = os.environ.get(
    "LLAMA_SERVER", os.path.expanduser("~/llama.cpp/build/bin/llama-server"))
PORT = int(os.environ.get("LLM_PORT", "8080"))
BAGLAM = int(os.environ.get("LLM_CTX", "32768"))
THREAD = int(os.environ.get("LLM_THREAD", str(max(4, (os.cpu_count() or 32) - 8))))
LOG = os.path.expanduser("~/llama-server-mtp.log")
KOK_URL = "http://127.0.0.1:%d" % PORT
TABAN = ("https://huggingface.co/unsloth/Qwen3.5-122B-A10B-MTP-GGUF"
         "/resolve/main/UD-Q4_K_XL/")

DOSYALAR = [
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf", 10943808),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00002-of-00003.gguf", 49667346080),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00003-of-00003.gguf", 28968190016),
]
TOPLAM = sum(b for _, b in DOSYALAR)


def indir(url, hedef, beklenen):
    """Kesintiye dayanikli indirme (HTTP Range ile devam eder)."""
    var_olan = os.path.getsize(hedef) if os.path.exists(hedef) else 0
    if var_olan == beklenen:
        print("   zaten tam, atlaniyor")
        return True
    if var_olan > beklenen:
        print("   bozuk (fazla buyuk), sifirdan indiriliyor")
        os.remove(hedef)
        var_olan = 0

    basliklar = {"Range": "bytes=%d-" % var_olan} if var_olan else {}
    if var_olan:
        print("   %.1f GiB mevcut, kaldigi yerden devam" % (var_olan / 1024 ** 3))
    istek = urllib.request.Request(url, headers=basliklar)
    t0 = time.time()
    indirilen = var_olan
    with urllib.request.urlopen(istek, timeout=60) as cevap, \
            open(hedef, "ab" if var_olan else "wb") as f:
        while True:
            parca = cevap.read(8 * 1024 * 1024)
            if not parca:
                break
            f.write(parca)
            indirilen += len(parca)
            gecen = time.time() - t0
            hiz = (indirilen - var_olan) / gecen / 1024 ** 2 if gecen > 0 else 0
            print("   %6.2f / %6.2f GiB  (%5.1f MB/s)"
                  % (indirilen / 1024 ** 3, beklenen / 1024 ** 3, hiz),
                  end="\r", flush=True)
    print()
    gercek = os.path.getsize(hedef)
    if gercek != beklenen:
        print("   HATA: boyut tutmuyor (%d != %d). Betigi tekrar calistirin." %
              (gercek, beklenen))
        return False
    return True


def istek_gonder(yol, govde=None, zaman_asimi=30):
    veri = json.dumps(govde).encode() if govde is not None else None
    r = urllib.request.Request(KOK_URL + yol, data=veri,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=zaman_asimi) as y:
        return json.loads(y.read().decode())


def ayakta_mi():
    try:
        istek_gonder("/health", zaman_asimi=5)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ 1) indir
print("=" * 66)
print("MTP SURUMU INDIRILIYOR (%.0f GiB)" % (TOPLAM / 1024 ** 3))
print("=" * 66)
os.makedirs(MTP_DIZIN, exist_ok=True)
bos = shutil.disk_usage(MTP_DIZIN).free
print("Hedef: %s" % MTP_DIZIN)
print("Bos disk: %.0f GiB" % (bos / 1024 ** 3))
if bos < TOPLAM * 1.05:
    print("HATA: yeterli disk yok.")
    sys.exit(1)

for ad, beklenen in DOSYALAR:
    print("\n-> %s (%.1f GiB)" % (ad, beklenen / 1024 ** 3))
    if not indir(TABAN + ad + "?download=true", os.path.join(MTP_DIZIN, ad), beklenen):
        sys.exit(1)
print("\nTum dosyalar tam.")

# ------------------------------------------------------- 2) yeniden baslatma
print("\n" + "=" * 66)
print("SUNUCU MTP ILE YENIDEN BASLATILIYOR")
print("=" * 66)
if ayakta_mi():
    print("Eski sunucu durduruluyor...")
    subprocess.run(["pkill", "-f", "llama-server"])
    time.sleep(5)

model = os.path.join(MTP_DIZIN, DOSYALAR[0][0])
komut = [BINARY, "-m", model, "-c", str(BAGLAM), "-t", str(THREAD),
         "--host", "127.0.0.1", "--port", str(PORT), "--jinja",
         "--spec-type", "draft-mtp", "--spec-draft-n-max", "6"]
print("  %s" % " ".join(komut))
with open(LOG, "ab") as log:
    subprocess.Popen(komut, stdout=log, stderr=subprocess.STDOUT,
                     stdin=subprocess.DEVNULL, start_new_session=True)

print("\nModel yukleniyor...")
basla = time.time()
while not ayakta_mi():
    gecen = time.time() - basla
    if gecen > 1200:
        print("\nHATA: acilmadi. Log sonu:")
        subprocess.run(["tail", "-30", LOG])
        print("\nIPUCU: llama.cpp surumunuz --spec-type destekliyor mu?")
        print("  %s --help | grep spec-type" % BINARY)
        sys.exit(1)
    print("  ... %3.0f sn" % gecen, end="\r", flush=True)
    time.sleep(5)
print("\nHAZIR! Yukleme: %.0f sn" % (time.time() - basla))

# ------------------------------------------------------------ 3) karsilastir
SORU = ("Sen bir veri analizi asistanisin. Kisa ve net cevap ver.\n"
        "Soru: Bir bankada kredi riski modellemesinde PD, LGD ve EAD "
        "kavramlarini birer cumleyle acikla.")
govde = {"messages": [{"role": "user", "content": SORU}], "max_tokens": 300,
         "chat_template_kwargs": {"enable_thinking": False},
         "temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5}

print("\n" + "=" * 66)
print("AYNI SORU (MTP ile)")
print("=" * 66)
t0 = time.time()
cevap = istek_gonder("/v1/chat/completions", govde, zaman_asimi=1800)
sure = time.time() - t0
uretilen = cevap.get("usage", {}).get("completion_tokens", 0)
hiz = uretilen / sure if sure else 0

print(cevap["choices"][0]["message"]["content"].strip())
print("\n--- KARSILASTIRMA ---")
print("MTP'siz (onceki olcum) : 5.80 token/sn")
print("MTP ile                : %.2f token/sn  (%s)" %
      (hiz, "%.1fx hizlanma" % (hiz / 5.80) if hiz else "-"))
print("Sure: %.1f sn | Uretilen: %d token" % (sure, uretilen))
print("\nSunucu ayakta: %s/v1" % KOK_URL)
