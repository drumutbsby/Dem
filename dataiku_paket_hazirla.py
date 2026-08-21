#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_paket_hazirla.py — Test sunucusuna tasima paketi hazirlar.

VERI managed folder'i icinde KURULUM/ klasoru olusturur ve icine:
  - Derlenmis llama.cpp ikililerini (tar.gz)          -> test sunucusunda derleme gerekmez
  - Istege bagli llama.cpp kaynak kodunu (tar.gz)     -> glibc uymazsa yeniden derlemek icin
  - MANIFEST.txt (ortam bilgisi, dosya listesi, SHA256)
  - README.txt   (test sunucusunda izlenecek adimlar)
koyar. GGUF model dosyalari zaten VERI'de; onlari da dogrular.

Dataiku Notebook icinde calistirin.

Ortam degiskenleri:
  KAYNAK_DAHIL=1   llama.cpp kaynak kodunu da pakete ekle (~200 MB)
  HASH=1           GGUF dosyalarinin SHA256'sini hesapla (73 GB -> ~10-20 dk,
                   ama Z: uzerinden tasima sonrasi butunluk kontrolu icin degerli)
"""

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import time

KLASOR = os.environ.get(
    "LLM_KLASOR", "/data/dataiku/DATA_DIR/managed_folders/UMUT/NwPGcMBJ")
PAKET = os.path.join(KLASOR, "KURULUM")
LLAMA_KOK = os.environ.get("LLAMA_KOK", os.path.expanduser("~/llama.cpp"))
BIN_DIZIN = os.path.join(LLAMA_KOK, "build", "bin")
KAYNAK_DAHIL = os.environ.get("KAYNAK_DAHIL") == "1"
HASH_YAP = os.environ.get("HASH") == "1"

GGUF_DOSYALAR = [
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf", 10943552),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00002-of-00003.gguf", 49640779424),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00003-of-00003.gguf", 27378273056),
]


def gb(b):
    return "%.2f GiB" % (b / 1024.0 ** 3)


def mb(b):
    return "%.1f MB" % (b / 1024.0 ** 2)


def komut(cmd, cwd=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=cwd)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def sha256(yol, etiket=""):
    h = hashlib.sha256()
    boyut = os.path.getsize(yol)
    okunan = 0
    t0 = time.time()
    with open(yol, "rb") as f:
        while True:
            parca = f.read(16 * 1024 * 1024)
            if not parca:
                break
            h.update(parca)
            okunan += len(parca)
            if boyut > 1024 ** 3:
                print("   %s %5.1f%% (%.0f sn)" %
                      (etiket, 100.0 * okunan / boyut, time.time() - t0),
                      end="\r", flush=True)
    if boyut > 1024 ** 3:
        print(" " * 60, end="\r")
    return h.hexdigest()


def main():
    print("=" * 68)
    print("TEST SUNUCUSU TASIMA PAKETI")
    print("=" * 68)

    if not os.path.isdir(BIN_DIZIN):
        print("HATA: llama.cpp derlenmis dizini yok -> %s" % BIN_DIZIN)
        print("Once dataiku_llm_kur.py betigini calistirin.")
        return
    os.makedirs(PAKET, exist_ok=True)
    print("Paket klasoru: %s\n" % PAKET)

    satirlar = []   # MANIFEST icerigi
    paket_dosyalari = []

    # --- 1) ortam bilgisi
    glibc = ""
    try:
        glibc = os.confstr("CS_GNU_LIBC_VERSION") or ""
    except Exception:
        pass
    surum = komut([os.path.join(BIN_DIZIN, "llama-server"), "--version"])
    commit = komut(["git", "rev-parse", "--short", "HEAD"], cwd=LLAMA_KOK)
    gcc = komut(["gcc", "-dumpfullversion"])
    bayraklar = []
    try:
        with open("/proc/cpuinfo") as f:
            metin = f.read().lower()
        bayraklar = [b for b in ("avx2", "avx512f", "avx512_vnni", "f16c")
                     if b in metin]
    except Exception:
        pass

    satirlar += [
        "KAYNAK SUNUCU ORTAMI",
        "  Isletim sistemi : %s %s" % (platform.system(), platform.release()),
        "  glibc           : %s" % (glibc or "?"),
        "  gcc             : %s" % (gcc or "?"),
        "  CPU bayraklari  : %s" % (", ".join(bayraklar) or "?"),
        "  llama.cpp commit: %s" % (commit or "?"),
        "  llama-server    : %s" % (surum.splitlines()[0] if surum else "?"),
        "",
        "UYARI: Ikililer bu ortamda derlendi. Test sunucusunda glibc surumu",
        "DAHA ESKI ise ikililer calismaz; o zaman kaynak koddan derleyin",
        "(KAYNAK_DAHIL=1 ile paketlediyseniz kaynak da bu klasorde).",
        "",
    ]
    print("Ortam: glibc %s | gcc %s | %s" % (glibc, gcc, ", ".join(bayraklar)))

    # --- 2) ikilileri paketle
    print("\n1) llama.cpp ikilileri paketleniyor...")
    bin_tar = os.path.join(PAKET, "llama-cpp-ikililer-rhel9-x64.tar.gz")
    with tarfile.open(bin_tar, "w:gz") as t:
        t.add(BIN_DIZIN, arcname="llama-cpp-bin")
    boyut = os.path.getsize(bin_tar)
    print("   %s (%s)" % (os.path.basename(bin_tar), mb(boyut)))
    paket_dosyalari.append((bin_tar, boyut))

    # --- 3) istege bagli kaynak kod
    if KAYNAK_DAHIL:
        print("\n2) llama.cpp kaynak kodu paketleniyor...")
        src_tar = os.path.join(PAKET, "llama-cpp-kaynak.tar.gz")

        def filtre(ti):
            # build ciktilarini ve git gecmisini disla
            for hariç in ("/build", "/.git"):
                if hariç in ti.name:
                    return None
            return ti

        with tarfile.open(src_tar, "w:gz") as t:
            t.add(LLAMA_KOK, arcname="llama.cpp", filter=filtre)
        boyut = os.path.getsize(src_tar)
        print("   %s (%s)" % (os.path.basename(src_tar), mb(boyut)))
        paket_dosyalari.append((src_tar, boyut))
    else:
        print("\n2) Kaynak kod atlandi (eklemek icin: KAYNAK_DAHIL=1)")

    # --- 4) GGUF dogrulama
    print("\n3) Model dosyalari dogrulaniyor...")
    satirlar.append("MODEL DOSYALARI (VERI klasorunun kokunde)")
    toplam_model = 0
    eksik = False
    for ad, beklenen in GGUF_DOSYALAR:
        yol = os.path.join(KLASOR, ad)
        if not os.path.exists(yol):
            print("   EKSIK: %s" % ad)
            satirlar.append("  EKSIK: %s" % ad)
            eksik = True
            continue
        gercek = os.path.getsize(yol)
        durum = "TAM" if gercek == beklenen else "BOYUT UYUSMUYOR"
        if gercek != beklenen:
            eksik = True
        print("   %-52s %12s  %s" % (ad[-52:], gb(gercek), durum))
        toplam_model += gercek
        satir = "  %s  %d bayt  %s" % (ad, gercek, durum)
        if HASH_YAP:
            ozet = sha256(yol, ad[-30:])
            satir += "\n    sha256: %s" % ozet
            print("      sha256: %s" % ozet)
        satirlar.append(satir)
    satirlar.append("")

    # --- 5) paket dosyalarinin ozeti
    satirlar.append("PAKET DOSYALARI (KURULUM klasorunde)")
    for yol, boyut in paket_dosyalari:
        satirlar.append("  %s  %d bayt\n    sha256: %s"
                        % (os.path.basename(yol), boyut, sha256(yol)))
    satirlar.append("")

    # --- 6) MANIFEST ve README
    with open(os.path.join(PAKET, "MANIFEST.txt"), "w") as f:
        f.write("\n".join(satirlar))

    readme = """TEST SUNUCUSU KURULUM ADIMLARI
================================================================

Bu klasordeki dosyalar + VERI klasorundeki 3 adet .gguf dosyasi
test sunucusuna kopyalanmalidir. Toplam: yaklasik %s

ADIM 1 - Dosyalari yerlestirin
  mkdir -p ~/qwen/model
  # 3 adet .gguf dosyasini ~/qwen/model/ icine kopyalayin
  # llama-cpp-ikililer-rhel9-x64.tar.gz dosyasini ~/qwen/ icine kopyalayin

ADIM 2 - Ikilileri acin
  cd ~/qwen && tar xzf llama-cpp-ikililer-rhel9-x64.tar.gz
  ./llama-cpp-bin/llama-server --version
  # "GLIBC_2.xx not found" hatasi alirsaniz ikililer uyumsuz demektir:
  # llama-cpp-kaynak.tar.gz varsa acip su komutlarla derleyin:
  #   cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF -DGGML_NATIVE=ON
  #   cmake --build build --config Release -j $(nproc) --target llama-server

ADIM 3 - Butunluk kontrolu (Z: uzerinden tasima sonrasi onerilir)
  sha256sum ~/qwen/model/*.gguf
  # Ciktilari MANIFEST.txt icindeki degerlerle karsilastirin
  # (MANIFEST'te sha256 yoksa en azindan dosya boyutlarini karsilastirin)

ADIM 4 - Sunucuyu baslatin
  cd ~/qwen
  nohup ./llama-cpp-bin/llama-server \\
    -m model/Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf \\
    -c 32768 -t $(nproc) -tb $(( $(nproc) - 4 )) \\
    --host 127.0.0.1 --port 8080 --jinja \\
    > llama-server.log 2>&1 &

  # Yalnizca -00001 dosyasi verilir, digerlerini kendisi bulur.
  # Ilk acilis 1-2 dakika surer. Hazir oldugunu su komutla dogrulayin:
  #   curl http://127.0.0.1:8080/health

ADIM 5 - Dataiku baglantisi
  Administration > Connections > NEW CONNECTION > LLM Mesh > OpenAI
    Base URL : http://127.0.0.1:8080/v1
    API key  : local
    Model id : qwen3.5-122b
  Permissions bolumunde ilgili projeye/gruba erisim verin.

DONANIM GEREKSINIMI
  RAM  : en az 90 GB bos (model 71.7 GiB + 32K baglam icin ~3 GiB KV cache)
  Disk : en az 80 GB
  CPU  : AVX2 sart, AVX-512 varsa daha hizli
  GPU  : gerekmez

OLCULEN PERFORMANS (kaynak sunucu: Xeon Gold 6342, 32 vCPU, 127 GB RAM)
  Uretim hizi   : 6.85 token/sn
  Model yukleme : ~66 saniye
  NOT: MTP spekulatif kod cozme CPU'da YAVASLATIYOR (0.63x), kullanmayin.
""" % gb(toplam_model + sum(b for _, b in paket_dosyalari))

    with open(os.path.join(PAKET, "README.txt"), "w") as f:
        f.write(readme)

    # --- ozet
    paket_toplam = sum(b for _, b in paket_dosyalari)
    print("\n" + "=" * 68)
    print("PAKET HAZIR")
    print("=" * 68)
    print("Klasor: %s" % PAKET)
    for yol, boyut in paket_dosyalari:
        print("  %-42s %10s" % (os.path.basename(yol), mb(boyut)))
    print("  %-42s %10s" % ("MANIFEST.txt", "-"))
    print("  %-42s %10s" % ("README.txt", "-"))
    print("\nZ: dizinine cekilecek toplam: %s" % gb(toplam_model + paket_toplam))
    print("  - KURULUM/ klasoru      : %s" % mb(paket_toplam))
    print("  - 3 adet .gguf (VERI kok): %s" % gb(toplam_model))
    if eksik:
        print("\nUYARI: model dosyalarinda eksik/boyut uyusmazligi var, yukariya bakin.")
    if not HASH_YAP:
        print("\nIPUCU: Tasima sonrasi butunluk kontrolu icin SHA256 uretmek isterseniz")
        print("       HASH=1 ile tekrar calistirin (73 GB icin ~10-20 dakika).")
    print("\nDataiku'da VERI klasorunu acip KURULUM/ icerigini ve 3 .gguf'u indirin.")


main()
