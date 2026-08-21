#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_hiz_ayari.py — CPU'da gercek hiz kazancini OLCEREK bulur.

MTP spekulatif kod cozme CPU + MoE kombinasyonunda ters teptigi icin
(olculen: 5.80 -> 3.63 tok/sn), asil kazanc thread sayisi ve NUMA
yerlesiminde. Bu betik llama-bench ile bunlari tarar.

llama-bench modeli BIR KEZ yukler, tum kombinasyonlari uzerinde dener;
o yuzden sunucuyu tekrar tekrar acip kapamaktan cok daha hizlidir.

Sure: ~10-20 dakika (model yukleme + her kombinasyon icin uretim testi).
"""

import os
import re
import subprocess
import sys

KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
# MTP'siz orijinal model (MTP katmanlari bosuna RAM yemesin)
MODEL = os.environ.get(
    "LLM_MODEL",
    os.path.join(KLASOR, "Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf"))
BENCH = os.environ.get(
    "LLAMA_BENCH", os.path.expanduser("~/llama.cpp/build/bin/llama-bench"))
THREADLER = os.environ.get("LLM_THREADLER", "16,20,24,28,32")
URETIM = os.environ.get("LLM_TG", "64")   # olculecek uretim token sayisi
PROMPT = os.environ.get("LLM_PP", "128")  # prefill testi icin girdi uzunlugu


def calistir(cmd):
    print("\n$ %s\n" % " ".join(cmd), flush=True)
    satirlar = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for satir in p.stdout:
        satir = satir.rstrip()
        satirlar.append(satir)
        if satir.startswith("|") or "error" in satir.lower():
            print(satir, flush=True)
    p.wait()
    return p.returncode, satirlar


def tabloyu_ayikla(satirlar):
    """llama-bench markdown tablosundan (test, threads, t/s) uclusu cikar."""
    sonuc = []
    for s in satirlar:
        if not s.startswith("|") or "---" in s or "t/s" in s:
            continue
        hucre = [h.strip() for h in s.strip("|").split("|")]
        if len(hucre) < 4:
            continue
        test = next((h for h in hucre if re.match(r"^(pp|tg)\d+", h)), None)
        hiz = next((h for h in hucre if re.match(r"^\d+\.\d+\s*±", h)), None)
        thread = None
        for h in hucre:
            if re.match(r"^\d+$", h) and 1 <= int(h) <= 256:
                thread = int(h)
        if test and hiz:
            sonuc.append((test, thread, float(hiz.split("±")[0].strip())))
    return sonuc


print("=" * 66)
print("LLAMA.CPP HIZ AYARI (llama-bench)")
print("=" * 66)
for yol, ad in [(BENCH, "llama-bench"), (MODEL, "model")]:
    if not os.path.exists(yol):
        print("HATA: %s bulunamadi -> %s" % (ad, yol))
        sys.exit(1)
print("Model   : %s" % os.path.basename(MODEL))
print("Threadler: %s" % THREADLER)

# Sunucu ayaktaysa RAM'i paylasmasin diye uyar
try:
    if subprocess.run(["pgrep", "-f", "llama-server"],
                      capture_output=True).returncode == 0:
        print("\nUYARI: llama-server calisiyor. Olcum bozulmamasi icin once durdurun:")
        print("  pkill -f llama-server")
        if not os.environ.get("YINE_DE"):
            print("Yine de devam etmek icin: YINE_DE=1 ile calistirin.")
            sys.exit(1)
except Exception:
    pass

# --numa destegi var mi?
yardim = subprocess.run([BENCH, "--help"], capture_output=True, text=True)
numa_var = "--numa" in (yardim.stdout + yardim.stderr)

print("\n--- 1/2: Thread taramasi ---")
kod, satirlar = calistir([BENCH, "-m", MODEL, "-t", THREADLER,
                          "-n", URETIM, "-p", PROMPT, "-r", "2"])
if kod != 0:
    print("HATA: llama-bench basarisiz. Son satirlar:")
    for s in satirlar[-20:]:
        print("  " + s)
    sys.exit(1)

olcumler = tabloyu_ayikla(satirlar)
uretim = [(t, h) for test, t, h in olcumler if test.startswith("tg")]
prefill = [(t, h) for test, t, h in olcumler if test.startswith("pp")]

print("\n--- URETIM HIZI (token/sn, yuksek olan iyi) ---")
for t, h in sorted(uretim, key=lambda x: -x[1]):
    print("  %2s thread : %6.2f tok/sn %s" % (t, h, "<-- en iyi" if (t, h) == max(uretim, key=lambda x: x[1]) else ""))
en_iyi_thread = max(uretim, key=lambda x: x[1])[0] if uretim else 24
en_iyi_hiz = max(uretim, key=lambda x: x[1])[1] if uretim else 0

if prefill:
    print("\n--- PREFILL HIZI (uzun girdi okuma) ---")
    for t, h in sorted(prefill, key=lambda x: -x[1]):
        print("  %2s thread : %7.1f tok/sn" % (t, h))

# --- 2/2: NUMA
numa_hiz = None
if numa_var:
    print("\n--- 2/2: NUMA yerlesimi (--numa distribute) ---")
    kod, satirlar = calistir([BENCH, "-m", MODEL, "-t", str(en_iyi_thread),
                              "-n", URETIM, "-p", "0", "-r", "2",
                              "--numa", "distribute"])
    if kod == 0:
        n = [(t, h) for test, t, h in tabloyu_ayikla(satirlar) if test.startswith("tg")]
        if n:
            numa_hiz = max(h for _, h in n)
            print("  --numa distribute : %6.2f tok/sn" % numa_hiz)
else:
    print("\n(2/2 atlandi: bu llama-bench surumunde --numa yok)")

# ------------------------------------------------------------------ ozet
print("\n" + "=" * 66)
print("SONUC")
print("=" * 66)
print("Onceki ayar (-t 24, MTP'siz) : 5.80 tok/sn")
print("En iyi thread sayisi         : %d  -> %.2f tok/sn" % (en_iyi_thread, en_iyi_hiz))
if numa_hiz:
    print("NUMA distribute ile          : %.2f tok/sn" % numa_hiz)
kazanc = (max(en_iyi_hiz, numa_hiz or 0) / 5.80) if en_iyi_hiz else 0
print("Toplam kazanc                : %.2fx" % kazanc)

numa_ek = " --numa distribute" if (numa_hiz and numa_hiz > en_iyi_hiz) else ""
print("\nOnerilen baslatma komutu:")
print("  ~/llama.cpp/build/bin/llama-server \\")
print("    -m %s \\" % MODEL)
print("    -c 32768 -t %d --host 127.0.0.1 --port 8080 --jinja%s"
      % (en_iyi_thread, numa_ek))
print("\n(Bunu dataiku_llm_baslat.py ile calistirmak icin:")
print("   LLM_THREAD=%d python dataiku_llm_baslat.py )" % en_iyi_thread)
