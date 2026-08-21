#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_hiz_ayari.py — CPU'da gercek hiz kazancini OLCEREK bulur.

MTP spekulatif kod cozme CPU + MoE kombinasyonunda ters teptigi icin
(olculen: 5.80 -> 3.63 tok/sn), asil kazanc thread sayisi ve NUMA
yerlesiminde. Bu betik llama-bench ile bunlari tarar.

Akis:
  1) Calisan llama-server'i durdurur (iki model ayni anda RAM'e sigmaz)
  2) llama-bench ile thread taramasi + NUMA testi yapar (model bir kez yuklenir)
  3) En iyi ayarla sunucuyu MTP'siz orijinal modelle yeniden baslatir

Sure: ~15-25 dakika. Notebook'ta calistirilabilir (sys.exit kullanmaz).

Ortam degiskenleri:
  LLM_THREADLER=16,24,32   taranacak thread sayilari
  YENIDEN_BASLATMA=0       olcum sonrasi sunucuyu baslatma
"""

import os
import re
import subprocess
import time

KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
# MTP'siz orijinal model (MTP CPU'da yavaslattigi icin varsayilan bu)
MODEL = os.environ.get(
    "LLM_MODEL",
    os.path.join(KLASOR, "Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf"))
BENCH = os.environ.get(
    "LLAMA_BENCH", os.path.expanduser("~/llama.cpp/build/bin/llama-bench"))
SERVER = os.environ.get(
    "LLAMA_SERVER", os.path.expanduser("~/llama.cpp/build/bin/llama-server"))
THREADLER = os.environ.get("LLM_THREADLER", "16,20,24,28,32")
URETIM = os.environ.get("LLM_TG", "64")
PROMPT = os.environ.get("LLM_PP", "128")
PORT = int(os.environ.get("LLM_PORT", "8080"))
BAGLAM = int(os.environ.get("LLM_CTX", "32768"))
LOG = os.path.expanduser("~/llama-server.log")
TABAN_HIZ = 5.80  # onceki olcum: -t 24, MTP'siz


def calistir(cmd, sessiz=False):
    print("\n$ %s\n" % " ".join(cmd), flush=True)
    satirlar = []
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         text=True, bufsize=1)
    for satir in p.stdout:
        satir = satir.rstrip()
        satirlar.append(satir)
        if not sessiz and (satir.startswith("|") or "error" in satir.lower()):
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


def sunucuyu_durdur():
    """Calisan llama-server'i durdur; RAM bosalana kadar bekle."""
    r = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    print("Calisan llama-server durduruluyor (olcum icin RAM gerekli)...")
    subprocess.run(["pkill", "-f", "llama-server"])
    for _ in range(60):
        time.sleep(1)
        if subprocess.run(["pgrep", "-f", "llama-server"],
                          capture_output=True).returncode != 0:
            print("durduruldu.\n")
            return True
    print("UYARI: surec hala kapanmadi, yine de devam ediliyor.\n")
    return True


def main():
    print("=" * 66)
    print("LLAMA.CPP HIZ AYARI (llama-bench)")
    print("=" * 66)
    for yol, ad in [(BENCH, "llama-bench"), (MODEL, "model")]:
        if not os.path.exists(yol):
            print("HATA: %s bulunamadi -> %s" % (ad, yol))
            return
    print("Model    : %s" % os.path.basename(MODEL))
    print("Threadler: %s" % THREADLER)
    print()

    sunucu_calisiyordu = sunucuyu_durdur()

    # --- 1/2: thread taramasi
    print("--- 1/2: Thread taramasi (model bir kez yuklenir, ~10 dk) ---")
    kod, satirlar = calistir([BENCH, "-m", MODEL, "-t", THREADLER,
                              "-n", URETIM, "-p", PROMPT, "-r", "2"])
    if kod != 0:
        print("HATA: llama-bench basarisiz. Son satirlar:")
        for s in satirlar[-20:]:
            print("  " + s)
        return

    olcumler = tabloyu_ayikla(satirlar)
    uretim = [(t, h) for test, t, h in olcumler if test.startswith("tg")]
    prefill = [(t, h) for test, t, h in olcumler if test.startswith("pp")]
    if not uretim:
        print("HATA: olcum tablosu okunamadi. Ham cikti:")
        for s in satirlar[-25:]:
            print("  " + s)
        return

    en_iyi_thread, en_iyi_hiz = max(uretim, key=lambda x: x[1])
    print("\n--- URETIM HIZI (token/sn, yuksek olan iyi) ---")
    for t, h in sorted(uretim, key=lambda x: -x[1]):
        isaret = "  <-- en iyi" if t == en_iyi_thread else ""
        print("  %2s thread : %6.2f tok/sn%s" % (t, h, isaret))
    if prefill:
        print("\n--- PREFILL (uzun girdi okuma, token/sn) ---")
        for t, h in sorted(prefill, key=lambda x: -x[1]):
            print("  %2s thread : %7.1f" % (t, h))

    # --- 2/2: NUMA
    numa_hiz = None
    yardim = subprocess.run([BENCH, "--help"], capture_output=True, text=True)
    if "--numa" in (yardim.stdout + yardim.stderr):
        print("\n--- 2/2: NUMA yerlesimi (--numa distribute) ---")
        kod, satirlar = calistir([BENCH, "-m", MODEL, "-t", str(en_iyi_thread),
                                  "-n", URETIM, "-p", "0", "-r", "2",
                                  "--numa", "distribute"])
        if kod == 0:
            n = [h for test, _, h in tabloyu_ayikla(satirlar) if test.startswith("tg")]
            if n:
                numa_hiz = max(n)
                fark = (numa_hiz / en_iyi_hiz - 1) * 100
                print("  --numa distribute : %6.2f tok/sn  (%+.0f%%)" % (numa_hiz, fark))
    else:
        print("\n(2/2 atlandi: bu llama-bench surumunde --numa yok)")

    numa_iyi = bool(numa_hiz and numa_hiz > en_iyi_hiz * 1.02)
    nihai_hiz = numa_hiz if numa_iyi else en_iyi_hiz

    # --- ozet
    print("\n" + "=" * 66)
    print("SONUC")
    print("=" * 66)
    print("Referans (-t 24, MTP'siz)  : %.2f tok/sn" % TABAN_HIZ)
    print("En iyi thread              : %d -> %.2f tok/sn" % (en_iyi_thread, en_iyi_hiz))
    if numa_hiz:
        print("NUMA distribute            : %.2f tok/sn %s"
              % (numa_hiz, "(kullanilacak)" if numa_iyi else "(faydasiz, kapali)"))
    print("Toplam kazanc              : %.2fx" % (nihai_hiz / TABAN_HIZ))

    komut = [SERVER, "-m", MODEL, "-c", str(BAGLAM), "-t", str(en_iyi_thread),
             "--host", "127.0.0.1", "--port", str(PORT), "--jinja"]
    if numa_iyi:
        komut += ["--numa", "distribute"]
    print("\nOnerilen baslatma komutu:\n  %s" % " ".join(komut))

    # --- yeniden baslatma
    if os.environ.get("YENIDEN_BASLATMA", "1") == "0":
        print("\n(Sunucu baslatilmadi: YENIDEN_BASLATMA=0)")
        return
    if not sunucu_calisiyordu and os.environ.get("YENIDEN_BASLATMA") is None:
        print("\n(Onceden sunucu calismiyordu, baslatilmadi.")
        print(" Baslatmak icin: YENIDEN_BASLATMA=1 ile tekrar calistirin)")
        return

    print("\nSunucu en iyi ayarla yeniden baslatiliyor...")
    with open(LOG, "ab") as log:
        subprocess.Popen(komut, stdout=log, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    import urllib.request
    basla = time.time()
    while time.time() - basla < 900:
        try:
            urllib.request.urlopen("http://127.0.0.1:%d/health" % PORT, timeout=5)
            print("HAZIR! (%.0f sn) -> http://127.0.0.1:%d/v1"
                  % (time.time() - basla, PORT))
            return
        except Exception:
            print("  ... %3.0f sn" % (time.time() - basla), end="\r", flush=True)
            time.sleep(5)
    print("\nUYARI: sunucu 15 dakikada acilmadi, log: %s" % LOG)


main()
