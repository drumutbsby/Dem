#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_kur.py — ADIM 1: llama.cpp'yi kaynaktan derler.

Sunucu RHEL 9 / glibc 2.34 oldugu icin hazir 'ubuntu-x64' binary calismaz;
bu betik gcc 11.5 + cmake 3.31 ile yerel derleme yapar (AVX-512 acik).

Dataiku > Notebooks > New Python notebook icine yapistirip calistirin.
Suresi: ~5-10 dakika. Tekrar calistirmak zararsizdir (derlenmisse atlar).
"""

import os
import subprocess
import sys

KOK = os.environ.get("LLAMA_KOK", os.path.expanduser("~/llama.cpp"))
BINARY = os.path.join(KOK, "build", "bin", "llama-server")
IS_PARCACIK = min(32, os.cpu_count() or 8)


def calistir(cmd, cwd=None):
    """Komutu calistir, ciktisini canli bas. Basarisizsa False doner."""
    print("\n$ %s\n" % " ".join(cmd), flush=True)
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1)
    son_satirlar = []
    for satir in p.stdout:
        satir = satir.rstrip()
        son_satirlar.append(satir)
        # derleme ciktisi cok uzun; ilerleme yuzdesi ve hatalari goster
        if satir.startswith("[") or "error" in satir.lower() or "Error" in satir:
            print(satir, flush=True)
    p.wait()
    if p.returncode != 0:
        print("\n!!! Komut basarisiz (cikis kodu %d). Son satirlar:" % p.returncode)
        for s in son_satirlar[-25:]:
            print("   " + s)
        return False
    return True


print("=" * 66)
print("LLAMA.CPP DERLEME")
print("=" * 66)
print("Hedef dizin : %s" % KOK)
print("Cekirdek    : %d" % IS_PARCACIK)

if os.path.exists(BINARY):
    print("\nllama-server ZATEN DERLENMIS: %s" % BINARY)
    print("Yeniden derlemek icin once su dizini silin: %s" % KOK)
    sys.exit(0)

# 1) kaynak kodu al
if not os.path.isdir(os.path.join(KOK, ".git")):
    print("\n--- 1/3: Kaynak kod indiriliyor (git clone) ---")
    if not calistir(["git", "clone", "--depth", "1",
                     "https://github.com/ggml-org/llama.cpp", KOK]):
        print("\nIPUCU: Kurumsal proxy arkasindaysaniz once sunu deneyin:")
        print("  git config --global http.proxy http://PROXY:PORT")
        sys.exit(1)
else:
    print("\n--- 1/3: Kaynak kod zaten mevcut, guncelleniyor ---")
    calistir(["git", "pull", "--ff-only"], cwd=KOK)

# 2) cmake yapilandirma
# LLAMA_CURL=OFF -> libcurl-devel yoksa derleme patlamasin (model dosyalari zaten yerel)
# GGML_NATIVE=ON -> Xeon Gold 6342'nin AVX-512 komutlarini kullan
print("\n--- 2/3: Yapilandirma (cmake) ---")
if not calistir(["cmake", "-B", "build",
                 "-DCMAKE_BUILD_TYPE=Release",
                 "-DLLAMA_CURL=OFF",
                 "-DGGML_NATIVE=ON"], cwd=KOK):
    print("\nIPUCU: AVX-512 kaynakli hata alirsaniz su ikisini deneyin:")
    print("  -DGGML_NATIVE=OFF -DGGML_AVX2=ON")
    sys.exit(1)

# 3) derleme
print("\n--- 3/3: Derleme (birkac dakika surer) ---")
if not calistir(["cmake", "--build", "build", "--config", "Release",
                 "-j", str(IS_PARCACIK),
                 "--target", "llama-server", "llama-cli", "llama-bench"], cwd=KOK):
    sys.exit(1)

print("\n" + "=" * 66)
if os.path.exists(BINARY):
    print("BASARILI: %s" % BINARY)
    surum = subprocess.run([BINARY, "--version"], capture_output=True, text=True)
    print((surum.stdout + surum.stderr).strip()[:300])
    print("\nSonraki adim: dataiku_llm_baslat.py betigini calistirin.")
else:
    print("HATA: binary olusmadi, yukaridaki cikti satirlarina bakin.")
    sys.exit(1)
