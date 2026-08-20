#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sistem_kontrol.py — Yerel LLM (Qwen3.8-27B) icin sistem uygunluk raporu.

Sadece Python standart kutuphanesini kullanir (pip ile kurulum gerekmez).
Python 3.8+ ile Windows / Linux / macOS uzerinde calisir.

Kullanim:
    python sistem_kontrol.py
"""

import ctypes
import os
import platform
import shutil
import subprocess
import sys

# Eski Windows konsollarinda Turkce karakter hatasini onle (cokme yerine '?')
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass


def run(cmd):
    """Bir komutu calistir; hata olursa bos metin dondur."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def get_ram_gb():
    """(toplam_GB, kullanilabilir_GB) dondurur; tespit edilemeyen None olur."""
    sistem = platform.system()
    try:
        if sistem == "Linux":
            bilgi = {}
            with open("/proc/meminfo") as f:
                for satir in f:
                    anahtar, _, deger = satir.partition(":")
                    bilgi[anahtar.strip()] = deger.strip()
            toplam = int(bilgi["MemTotal"].split()[0]) / 1024**2
            uygun = int(bilgi["MemAvailable"].split()[0]) / 1024**2
            return toplam, uygun
        if sistem == "Darwin":
            toplam = int(run(["sysctl", "-n", "hw.memsize"])) / 1024**3
            return toplam, None
        if sistem == "Windows":
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            durum = MEMORYSTATUSEX()
            durum.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(durum))
            return durum.ullTotalPhys / 1024**3, durum.ullAvailPhys / 1024**3
    except Exception:
        pass
    return None, None


def get_cpu_adi():
    sistem = platform.system()
    if sistem == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                for satir in f:
                    if satir.lower().startswith("model name"):
                        return satir.split(":", 1)[1].strip()
        except Exception:
            pass
    elif sistem == "Darwin":
        ad = run(["sysctl", "-n", "machdep.cpu.brand_string"])
        if ad:
            return ad
    elif sistem == "Windows":
        ad = run(["powershell", "-NoProfile", "-Command",
                  "(Get-CimInstance Win32_Processor).Name"])
        if ad:
            return ad.splitlines()[0].strip()
    return platform.processor() or platform.machine() or "bilinmiyor"


def get_cpu_ozellikleri():
    """AVX2 / AVX-512 destegi (llama.cpp'nin CPU hizi icin onemli)."""
    sistem = platform.system()
    if sistem == "Linux":
        try:
            with open("/proc/cpuinfo") as f:
                metin = f.read().lower()
            return "avx2" in metin, "avx512f" in metin
        except Exception:
            pass
    elif sistem == "Darwin":
        metin = (run(["sysctl", "-n", "machdep.cpu.leaf7_features"]) + " " +
                 run(["sysctl", "-n", "machdep.cpu.features"])).lower()
        if metin.strip():
            return "avx2" in metin, "avx512f" in metin
        if "arm" in platform.machine().lower():
            return None, None  # Apple Silicon: AVX yok ama NEON ile zaten hizli
    return None, None  # Windows'ta ek paket gerektirdigi icin tespit edilmiyor


def get_gpular():
    """[(ad, bellek_bilgisi), ...] listesi dondurur."""
    gpular = []
    cikti = run(["nvidia-smi", "--query-gpu=name,memory.total",
                 "--format=csv,noheader"])
    for satir in cikti.splitlines():
        parcalar = [p.strip() for p in satir.split(",")]
        if len(parcalar) >= 2:
            gpular.append((parcalar[0], parcalar[1]))
    if gpular:
        return gpular
    sistem = platform.system()
    if sistem == "Windows":
        cikti = run(["powershell", "-NoProfile", "-Command",
                     "(Get-CimInstance Win32_VideoController).Name"])
        return [(s.strip(), "VRAM bilinmiyor") for s in cikti.splitlines() if s.strip()]
    if sistem == "Linux":
        cikti = run(["sh", "-c", "lspci 2>/dev/null | grep -iE 'vga|3d|display'"])
        return [(s.split(":", 2)[-1].strip(), "VRAM bilinmiyor")
                for s in cikti.splitlines() if s.strip()]
    if sistem == "Darwin" and "arm" in platform.machine().lower():
        return [("Apple Silicon (birlesik bellek — GPU, RAM'i kullanir)", "RAM ile ortak")]
    return []


# Qwen3.8-27B GGUF secenekleri: (ad, dosya boyutu GB, kalite notu)
# Boyutlar unsloth/Qwen3.8-27B-GGUF ve ggml-org/Qwen3.8-27B-GGUF depolarindan (Agustos 2026).
QWEN_SECENEKLERI = [
    ("Q8_0            (neredeyse kayipsiz)", 29, "48 GB+ RAM"),
    ("UD-Q6_K_XL      (cok iyi kalite)", 25, "32-48 GB RAM"),
    ("UD-Q5_K_M       (iyi kalite)", 20, "32 GB RAM"),
    ("UD-Q4_K_M       (onerilen denge; Ollama varsayilani)", 16, "24-32 GB RAM"),
    ("UD-IQ3_XXS      (orta duzey kalite kaybi)", 11, "16-24 GB RAM"),
    ("UD-Q2_K_XL      (belirgin kalite kaybi)", 10, "16 GB RAM"),
    ("UD-IQ2_XXS      (ciddi kalite kaybi)", 7, "12-16 GB RAM"),
    ("UD-IQ1_S        (en kucuk; kalite cok duser)", 6, "8-12 GB RAM"),
]
EK_YUK_GB = 4  # isletim sistemi + KV onbellek + calisma payi


def main():
    toplam_ram, uygun_ram = get_ram_gb()
    cekirdek = os.cpu_count() or 0
    avx2, avx512 = get_cpu_ozellikleri()
    gpular = get_gpular()
    ev = os.path.expanduser("~")
    try:
        disk = shutil.disk_usage(ev)
        bos_disk = disk.free / 1024**3
    except Exception:
        bos_disk = None
    ollama_var = shutil.which("ollama") is not None

    def gb(deger):
        return f"{deger:.1f} GB" if deger is not None else "tespit edilemedi"

    print("=" * 62)
    print("SISTEM RAPORU")
    print("=" * 62)
    print(f"Isletim sistemi : {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Python          : {platform.python_version()}")
    print(f"CPU             : {get_cpu_adi()}")
    print(f"Cekirdek        : {cekirdek} mantiksal cekirdek")
    if avx2 is not None:
        print(f"AVX2 / AVX-512  : {'var' if avx2 else 'YOK'} / {'var' if avx512 else 'yok'}"
              + ("" if avx2 else "  (AVX2 yoksa llama.cpp cok yavaslar)"))
    print(f"RAM (toplam)    : {gb(toplam_ram)}")
    print(f"RAM (bos)       : {gb(uygun_ram)}")
    print(f"Bos disk ({ev}) : {gb(bos_disk)}")
    if gpular:
        for ad, bellek in gpular:
            print(f"GPU             : {ad} [{bellek}]")
    else:
        print("GPU             : bulunamadi (CPU + RAM ile calisilacak)")
    print(f"Ollama kurulu   : {'evet' if ollama_var else 'hayir'}")

    print()
    print("=" * 62)
    print("QWEN3.8-27B UYGUNLUK TABLOSU (GPU'suz: model RAM'e sigmali)")
    print("=" * 62)
    print(f"{'Surum':<52}{'Dosya':>7}{'Gerekli':>9}  Durum")
    print("-" * 78)

    en_iyi = None
    for ad, boyut, _ in QWEN_SECENEKLERI:
        gerekli = boyut + EK_YUK_GB
        if toplam_ram is None:
            durum = "RAM bilinmiyor"
        elif toplam_ram >= gerekli:
            durum = "UYGUN"
            if en_iyi is None:
                en_iyi = (ad, boyut)
        elif toplam_ram >= boyut + 2:
            durum = "SINIRDA (diger uygulamalari kapatin)"
        else:
            durum = "uymaz"
        print(f"{ad:<52}{boyut:>4} GB{gerekli:>6} GB  {durum}")

    print()
    print("=" * 62)
    print("SONUC VE ONERI")
    print("=" * 62)
    if toplam_ram is None:
        print("- RAM tespit edilemedi; tabloyu kendi RAM'inize gore okuyun.")
    elif en_iyi and en_iyi[1] >= 16:
        print(f"- Sisteminiz Qwen3.8-27B'yi kaldirir. Onerilen: UD-Q4_K_M (~16 GB).")
        print("  En kolay kurulum:  ollama run qwen3.8:27b   (~18 GB indirme)")
        if toplam_ram >= 33:
            print("- RAM'iniz bol: Q5/Q6 quantlar daha kaliteli ama CPU'da daha yavas olur.")
    elif en_iyi:
        print(f"- 27B ancak dusuk kaliteli quant ile sigar: {en_iyi[0].split()[0]} (~{en_iyi[1]} GB).")
        print("  Kalite kaybi belirgin olur. Daha kucuk bir model genelde daha iyi sonuc verir:")
        print("  ornegin Qwen3-8B (Q4 ~5 GB) veya Qwen3-4B (Q4 ~2.5 GB) -> ollama run qwen3:8b")
    else:
        print("- RAM'iniz 27B icin yetersiz. Onerim kucuk modeller veya bulut API:")
        print("  ollama run qwen3:4b  (~2.5 GB)  /  ollama run qwen3:8b  (~5 GB)")

    if not gpular or all("nvidia" not in ad.lower() for ad, _ in gpular):
        print("- HIZ UYARISI: GPU olmadan 27B yogun model tipik bir masaustu CPU'da")
        print("  yaklasik 1-3 token/sn uretir (RAM hizina bagli). Sohbet icin sabir ister;")
        print("  akici kullanim icin 4B-8B sinifi model veya 16 GB+ VRAM'li GPU gerekir.")
    if bos_disk is not None and en_iyi and bos_disk < en_iyi[1] + 5:
        print(f"- DISK UYARISI: Bos alan ({bos_disk:.0f} GB) secilen quant icin dar; yer acin.")
    print("- Ileride GPU alirsaniz: 24 GB VRAM (RTX 3090/4090) Q4_K_M'i tamamen")
    print("  GPU'ya yukler; 12-16 GB VRAM'de katmanlarin bir kismi RAM'de kalir.")
    print()
    print("Kaynak: docs/qwen3.8-27b-arastirma.md (boyutlar Hugging Face'ten dogrulandi)")


if __name__ == "__main__":
    main()
