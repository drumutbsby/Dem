#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_baslat.py — ADIM 2: modeli baslatir ve deneme sorusu sorar.

- llama-server'i notebook'tan BAGIMSIZ (detached) baslatir; notebook kapansa
  da sunucu ayakta kalir.
- Model yuklenene kadar bekler (71.7 GB -> ilk acilis birkac dakika surebilir).
- Turkce bir deneme sorusu sorar, cevabi ve token/sn hizini yazar.

Tekrar calistirmak zararsizdir: sunucu zaten calisiyorsa yeniden baslatmaz.
Durdurmak icin:  DURDUR=1 ile calistirin.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
MODEL = os.path.join(KLASOR, "Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf")
BINARY = os.environ.get(
    "LLAMA_SERVER", os.path.expanduser("~/llama.cpp/build/bin/llama-server"))
PORT = int(os.environ.get("LLM_PORT", "8080"))
BAGLAM = int(os.environ.get("LLM_CTX", "32768"))
# Olculen (llama-bench, 2026-08-21): uretim 32 thread'te en hizli (7.23 tok/sn),
# prefill 28 thread'te (73 tok/sn); 32'de cekismeden dusuyor. Bu yuzden ayri ayri.
THREAD = int(os.environ.get("LLM_THREAD", str(os.cpu_count() or 32)))
THREAD_BATCH = int(os.environ.get("LLM_THREAD_BATCH", str(max(1, (os.cpu_count() or 32) - 4))))
MLOCK = os.environ.get("LLM_MLOCK", "0") == "1"  
LOG = os.path.expanduser("~/llama-server.log")
KOK_URL = "http://127.0.0.1:%d" % PORT

# Unsloth/Qwen'in onerdigi ornekleme ayarlari (dusunmesiz/instruct mod)
ORNEKLEME = dict(temperature=0.7, top_p=0.8, presence_penalty=1.5)


def istek(yol, govde=None, zaman_asimi=30):
    url = KOK_URL + yol
    veri = json.dumps(govde).encode() if govde is not None else None
    r = urllib.request.Request(
        url, data=veri, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=zaman_asimi) as y:
        return json.loads(y.read().decode())


def ayakta_mi():
    try:
        istek("/health", zaman_asimi=5)
        return True
    except Exception:
        return False


def port_dolu_mu():
    s = socket.socket()
    s.settimeout(1)
    try:
        return s.connect_ex(("127.0.0.1", PORT)) == 0
    finally:
        s.close()


# --------------------------------------------------------------- durdurma
if os.environ.get("DURDUR"):
    print("llama-server durduruluyor...")
    subprocess.run(["pkill", "-f", "llama-server"])
    time.sleep(2)
    print("durduruldu." if not port_dolu_mu() else "hala calisiyor olabilir.")
    sys.exit(0)

print("=" * 66)
print("QWEN3.5-122B DENEMESI")
print("=" * 66)
print("Model   : %s" % os.path.basename(MODEL))
print("Binary  : %s" % BINARY)
print("Port    : %d | Baglam: %d token | Thread: %d (prefill %d)"
      % (PORT, BAGLAM, THREAD, THREAD_BATCH))

for yol, ad in [(BINARY, "llama-server"), (MODEL, "model dosyasi")]:
    if not os.path.exists(yol):
        print("\nHATA: %s bulunamadi -> %s" % (ad, yol))
        if ad == "llama-server":
            print("Once dataiku_llm_kur.py betigini calistirin.")
        sys.exit(1)

# --------------------------------------------------------------- baslatma
if ayakta_mi():
    print("\nSunucu ZATEN CALISIYOR, yeniden baslatilmadi.")
else:
    if port_dolu_mu():
        print("\nHATA: %d portu baska bir surec tarafindan kullaniliyor." % PORT)
        print("Baska port deneyin:  LLM_PORT=8081")
        sys.exit(1)
    komut = [BINARY, "-m", MODEL, "-c", str(BAGLAM),
             "-t", str(THREAD), "-tb", str(THREAD_BATCH),
             "--host", "127.0.0.1", "--port", str(PORT), "--jinja"]
    if MLOCK:
        komut.append("--mlock")  # sayfalar RAM'den tahliye edilmesin
    print("\nBaslatiliyor (arka planda):\n  %s" % " ".join(komut))
    print("Log dosyasi: %s" % LOG)
    with open(LOG, "ab") as log:
        subprocess.Popen(komut, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)

    print("\nModel yukleniyor (71.7 GB, ilk acilista birkac dakika surebilir)...")
    basla = time.time()
    while True:
        if ayakta_mi():
            print("\nHAZIR! Yukleme suresi: %.0f saniye" % (time.time() - basla))
            break
        gecen = time.time() - basla
        if gecen > 1200:
            print("\nHATA: 20 dakikada acilmadi. Log'un sonu:")
            subprocess.run(["tail", "-30", LOG])
            sys.exit(1)
        print("  ... %3.0f sn" % gecen, end="\r", flush=True)
        time.sleep(5)

# --------------------------------------------------------------- deneme
SORU = ("Sen bir veri analizi asistanisin. Kisa ve net cevap ver.\n"
        "Soru: Bir bankada kredi riski modellemesinde PD, LGD ve EAD "
        "kavramlarini birer cumleyle acikla.")

print("\n" + "=" * 66)
print("DENEME SORUSU GONDERILIYOR")
print("=" * 66)
print(SORU)

govde = {
    "messages": [{"role": "user", "content": SORU}],
    "max_tokens": 300,
    "chat_template_kwargs": {"enable_thinking": False},  # hizli cevap icin
}
govde.update(ORNEKLEME)

t0 = time.time()
try:
    cevap = istek("/v1/chat/completions", govde, zaman_asimi=1800)
except urllib.error.HTTPError as e:
    print("\nHATA %s: %s" % (e.code, e.read().decode()[:500]))
    sys.exit(1)
sure = time.time() - t0

metin = cevap["choices"][0]["message"]["content"]
kullanim = cevap.get("usage", {})
uretilen = kullanim.get("completion_tokens", 0)

print("\n--- MODELIN CEVABI ---")
print(metin.strip())
print("\n--- OLCUM ---")
print("Sure          : %.1f saniye" % sure)
print("Uretilen token: %s" % uretilen)
if uretilen and sure > 0:
    print("Hiz           : %.2f token/sn" % (uretilen / sure))
print("Girdi token   : %s" % kullanim.get("prompt_tokens", "?"))

print("\n" + "=" * 66)
print("SUNUCU AYAKTA KALDI -> %s/v1" % KOK_URL)
print("Dataiku LLM Mesh baglantisi icin bu adresi kullanin.")
print("Durdurmak icin: DURDUR=1 ile bu betigi tekrar calistirin.")
