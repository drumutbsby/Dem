#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_baslat.py — Qwen3.5-122B sunucusunu baslatir, sistem mesajiyla dener.

Dataiku Notebook icine yapistirip calistirin. Tekrar calistirmak zararsizdir:
sunucu istenen ayarlarla calisiyorsa dokunmaz, ayarlar farkliysa yeniden baslatir.

Ortam degiskenleri:
  DURDUR=1              sunucuyu durdur ve cik
  LLM_THREAD=28         uretim thread sayisi (olculen en iyi: 32)
  LLM_THREAD_BATCH=28   prefill thread sayisi (olculen en iyi: 28)
  LLM_CTX=131072        baglam uzunlugu (varsayilan 32768)
  LLM_MLOCK=1           model sayfalarini RAM'e kilitle
  DUSUNME=1             dusunme modunu ac (kalite artar, cevap dakikalar surer)
  SORU="..."            kendi deneme sorunuz
"""

import json
import os
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request

# ----------------------------------------------------------------- AYARLAR
KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
MODEL = os.environ.get(
    "LLM_MODEL",
    os.path.join(KLASOR, "Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf"))
BINARY = os.environ.get(
    "LLAMA_SERVER", os.path.expanduser("~/llama.cpp/build/bin/llama-server"))
PORT = int(os.environ.get("LLM_PORT", "8080"))
BAGLAM = int(os.environ.get("LLM_CTX", "32768"))
# Olculen (llama-bench, 21.08.2026): uretim 32 thread'te 7.23 tok/sn,
# prefill 28 thread'te 73 tok/sn (32'de cekismeden dusuyor). Bu yuzden ayri.
THREAD = int(os.environ.get("LLM_THREAD", str(os.cpu_count() or 32)))
THREAD_BATCH = int(os.environ.get("LLM_THREAD_BATCH",
                                  str(max(1, (os.cpu_count() or 32) - 4))))
MLOCK = os.environ.get("LLM_MLOCK", "0") == "1"
DUSUNME = os.environ.get("DUSUNME", "0") == "1"
LOG = os.path.expanduser("~/llama-server.log")
KOK_URL = "http://127.0.0.1:%d" % PORT

# ---------------------------------------------------- SISTEM MESAJI (PROMPT)
SISTEM_MESAJI = """Sen bir bankanin veri ve risk analitigi ekibine destek veren yapay zeka asistanisin.

DIL VE TERMINOLOJI
- Her zaman Turkce yanit ver. Yerlesik Turkce finans terminolojisini kullan,
  Ingilizce terimleri kelime kelime cevirme.
- Dogru karsiliklar: default = temerrut (asla "varsayilan"), exposure = risk tutari,
  PD = temerrut olasiligi, LGD = temerrut halinde kayip orani,
  EAD = temerrut anindaki risk tutari, recovery = tahsilat, collateral = teminat,
  provision = karsilik, impairment = deger dusuklugu, write-off = zarar kaydi,
  delinquency = gecikme, backtesting = geriye donuk test,
  overfitting = asiri ogrenme, feature = degisken, target = hedef degisken.
- Kisaltmalari ilk gectigi yerde ac: "PD (temerrut olasiligi)" gibi.

CEVAP BICIMI
- Dogrudan cevapla, girizgah yapma. Uzun konularda en fazla 4 madde kullan.
- Formulu duz metin olarak yaz: Beklenen Kayip (EL) = PD x LGD x EAD
  (LaTeX kullanma: $ isareti, \times, $$...$$ Dataiku arayuzunde render edilmez.)
- Kod istenirse Python/pandas ver, yorumlari Turkce yaz.

DOGRULUK
- Emin olmadigin sayisal deger, oran veya mevzuat maddesi UYDURMA;
  "bu deger dogrulanmali" de ve neyin dogrulanmasi gerektigini soyle.
- BDDK, Basel III, TFRS 9 gibi duzenlemelerde genel cerceveyi anlat,
  madde numarasi ve tarih uydurma.
- Varsayim yaptiysan varsayimi cevabin sonunda acikca belirt.

GIZLILIK
- Sana verilen musteri bilgisi, hesap numarasi veya tutari cevapta gereksiz yere
  tekrar etme; orneklerde gercek veri yerine temsili deger kullan."""

# Uretici onerisi (Qwen3.5 model karti): instruct / dusunmesiz mod
ORNEKLEME = {"temperature": 0.7, "top_p": 0.8, "presence_penalty": 1.5}
if DUSUNME:  # dusunme modu icin farkli parametreler onerilir
    ORNEKLEME = {"temperature": 1.0, "top_p": 0.95, "presence_penalty": 1.5}

VARSAYILAN_SORU = ("Bir bankada kredi riski modellemesinde PD, LGD ve EAD "
                   "kavramlarini birer cumleyle acikla ve beklenen kayip "
                   "formulunu yaz.")


# ------------------------------------------------------- YARDIMCI FONKSIYONLAR
def istek(yol, govde=None, zaman_asimi=30):
    veri = json.dumps(govde).encode() if govde is not None else None
    r = urllib.request.Request(KOK_URL + yol, data=veri,
                               headers={"Content-Type": "application/json"})
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


def sunucu_pidleri():
    """Gercekten llama-server olan sureclerin (pid, args) listesi.

    'pkill -f llama-server' KULLANILMAZ: komut satirinda bu metin gecen her
    sureci (ornegin bu betigi calistiran kabugu) oldururdu. Onun yerine her
    adayin /proc/<pid>/cmdline'ina bakip calistirilabilir dosya adini dogrularz.
    """
    pidler = []
    kendi = {os.getpid(), os.getppid()}
    r = subprocess.run(["pgrep", "-f", "llama-server"], capture_output=True, text=True)
    if r.returncode != 0:
        return pidler
    for parca in r.stdout.split():
        try:
            pid = int(parca)
        except ValueError:
            continue
        if pid in kendi:
            continue
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                args = [a for a in f.read().decode().split("\0") if a]
        except Exception:
            continue
        if args and os.path.basename(args[0]) == "llama-server":
            pidler.append((pid, args))
    return pidler


def calisan_args():
    """Calisan llama-server'in komut satiri (yoksa None)."""
    pidler = sunucu_pidleri()
    return pidler[0][1] if pidler else None


def arg_degeri(args, bayrak):
    try:
        return args[args.index(bayrak) + 1]
    except (ValueError, IndexError):
        return None


def sunucuyu_durdur():
    """llama-server sureclerini nazikce durdur, gerekirse zorla."""
    pidler = sunucu_pidleri()
    if not pidler:
        return False
    for pid, _ in pidler:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for _ in range(60):
        time.sleep(1)
        if not sunucu_pidleri():
            return True
    for pid, _ in sunucu_pidleri():   # hala duruyorsa zorla
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    time.sleep(2)
    return True


# ------------------------------------------------------------------ ANA AKIS
def main():
    if os.environ.get("DURDUR"):
        print("llama-server durduruluyor...")
        print("durduruldu." if sunucuyu_durdur() else "calisan llama-server yoktu.")
        return

    print("=" * 66)
    print("QWEN3.5-122B")
    print("=" * 66)
    print("Model   : %s" % os.path.basename(MODEL))
    print("Port    : %d | Baglam: %d | Thread: %d (prefill %d)"
          % (PORT, BAGLAM, THREAD, THREAD_BATCH))
    print("Dusunme : %s" % ("ACIK (yavas, kaliteli)" if DUSUNME else "kapali (hizli)"))

    for yol, ad in [(BINARY, "llama-server"), (MODEL, "model dosyasi")]:
        if not os.path.exists(yol):
            print("\nHATA: %s bulunamadi -> %s" % (ad, yol))
            if ad == "llama-server":
                print("Once dataiku_llm_kur.py betigini calistirin.")
            return

    # --- sunucu durumu: ayarlar uyusuyor mu?
    istenen = {"-m": MODEL, "-c": str(BAGLAM), "-t": str(THREAD),
               "-tb": str(THREAD_BATCH)}
    mevcut = calisan_args() if ayakta_mi() else None
    farklar = [(b, arg_degeri(mevcut, b), d) for b, d in istenen.items()
               if mevcut and arg_degeri(mevcut, b) != d]

    if mevcut and not farklar:
        print("\nSunucu ZATEN ISTENEN AYARLARLA CALISIYOR.")
    else:
        if mevcut:
            print("\nAyarlar farkli, sunucu yeniden baslatiliyor:")
            for bayrak, simdiki, hedef in farklar:
                print("   %-4s %s -> %s" % (bayrak, simdiki, hedef))
            sunucuyu_durdur()
        if port_dolu_mu():
            print("\nHATA: %d portu dolu. LLM_PORT=8081 ile deneyin." % PORT)
            return

        komut = [BINARY, "-m", MODEL, "-c", str(BAGLAM),
                 "-t", str(THREAD), "-tb", str(THREAD_BATCH),
                 "--host", "127.0.0.1", "--port", str(PORT), "--jinja"]
        if MLOCK:
            komut.append("--mlock")
        print("\nBaslatiliyor:\n  %s" % " ".join(komut))
        with open(LOG, "ab") as log:
            subprocess.Popen(komut, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)

        print("\nModel yukleniyor (71.7 GiB)...")
        basla = time.time()
        while not ayakta_mi():
            gecen = time.time() - basla
            if gecen > 1200:
                print("\nHATA: 20 dakikada acilmadi. Log sonu:")
                subprocess.run(["tail", "-30", LOG])
                return
            print("  ... %3.0f sn" % gecen, end="\r", flush=True)
            time.sleep(5)
        print("\nHAZIR! Yukleme: %.0f sn" % (time.time() - basla))

    # --- deneme sorusu
    soru = os.environ.get("SORU", VARSAYILAN_SORU)
    print("\n" + "=" * 66)
    print("DENEME SORUSU")
    print("=" * 66)
    print(soru)

    govde = {
        "messages": [{"role": "system", "content": SISTEM_MESAJI},
                     {"role": "user", "content": soru}],
        "max_tokens": 2000 if DUSUNME else 400,
        "chat_template_kwargs": {"enable_thinking": DUSUNME},
    }
    govde.update(ORNEKLEME)

    t0 = time.time()
    try:
        cevap = istek("/v1/chat/completions", govde, zaman_asimi=3600)
    except urllib.error.HTTPError as e:
        print("\nHATA %s: %s" % (e.code, e.read().decode()[:500]))
        return
    except Exception as e:
        print("\nHATA: %s" % e)
        return
    sure = time.time() - t0

    mesaj = cevap["choices"][0]["message"]
    dusunce = mesaj.get("reasoning_content") or ""
    kullanim = cevap.get("usage", {})
    uretilen = kullanim.get("completion_tokens", 0)

    if dusunce:
        print("\n--- DUSUNME (ilk 400 karakter) ---")
        print(dusunce.strip()[:400] + ("..." if len(dusunce) > 400 else ""))
    print("\n--- CEVAP ---")
    print((mesaj.get("content") or "").strip())

    print("\n--- OLCUM ---")
    print("Sure          : %.1f sn" % sure)
    print("Girdi token   : %s (sistem mesaji dahil)" % kullanim.get("prompt_tokens", "?"))
    print("Uretilen token: %s" % uretilen)
    if uretilen and sure:
        print("Hiz           : %.2f token/sn" % (uretilen / sure))

    print("\n" + "=" * 66)
    print("Sunucu ayakta -> %s/v1" % KOK_URL)
    print("Dataiku LLM Mesh: Base URL bu adres, API key 'local'.")
    print("Durdurmak icin: DURDUR=1 ile tekrar calistirin.")


main()
