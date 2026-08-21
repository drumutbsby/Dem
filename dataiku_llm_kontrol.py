#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dataiku_llm_kontrol.py — Qwen3.5-122B GGUF calistirma on-kontrolu.

Dataiku'da bir Python Notebook (veya Python recipe) icine yapistirip calistirin.
Sadece standart kutuphane kullanir. Python 3.6+ ile calisir.

Yaptigi kontroller:
  1) Managed folder'in (VERI) gercek disk yolu
  2) 3 GGUF parcasinin tam bayt boyutu dogrulamasi
  3) glibc surumu -> hazir llama.cpp binary'si uyar mi?
  4) Derleme araclari (gcc / cmake / make) var mi?
  5) Sunucuda internet cikisi var mi (HF ve GitHub)?
  6) RAM / disk / cekirdek durumu
  7) llama-server zaten kurulu mu?
Sonunda size ozel "sonraki adim" onerisi basar.
"""

import os
import platform
import shutil
import subprocess
import sys

# Dataiku managed folder adi (farkliysa degistirin) veya tam yolu LLM_KLASOR ile verin
FOLDER_ADI = os.environ.get("LLM_FOLDER_ADI", "VERI")

BEKLENEN_DOSYALAR = [
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00001-of-00003.gguf", 10943552),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00002-of-00003.gguf", 49640779424),
    ("Qwen3.5-122B-A10B-UD-Q4_K_XL-00003-of-00003.gguf", 27378273056),
]

sorunlar = []
notlar = []


def baslik(metin):
    print("\n" + "=" * 66)
    print(metin)
    print("=" * 66)


def komut(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return (r.stdout + r.stderr).strip()
    except Exception:
        return ""


def klasor_yolu_bul():
    """Managed folder'in disk yolunu bul; bulunamazsa None."""
    yol = os.environ.get("LLM_KLASOR")
    if yol:
        return yol, "LLM_KLASOR ortam degiskeni"
    try:
        import dataiku  # yalnizca DSS icinde bulunur
        f = dataiku.Folder(FOLDER_ADI)
        return f.get_path(), "dataiku.Folder('%s').get_path()" % FOLDER_ADI
    except Exception as e:
        notlar.append("dataiku modulu kullanilamadi (%s: %s)" % (type(e).__name__, e))
    return None, None


def gb(bayt):
    return "%.2f GB" % (bayt / 1024.0 ** 3)


# ---------------------------------------------------------------- 1) klasor
baslik("1) MODEL KLASORU")
klasor, kaynak = klasor_yolu_bul()
if klasor:
    print("Yol      : %s" % klasor)
    print("Kaynak   : %s" % kaynak)
    print("Mevcut mu: %s" % ("evet" if os.path.isdir(klasor) else "HAYIR"))
else:
    print("Managed folder yolu bulunamadi.")
    print("Bu betigi Dataiku Notebook icinde calistirin, ya da yolu elle verin:")
    print("  LLM_KLASOR=/veri/dataiku/.../NwPGcMBJ python dataiku_llm_kontrol.py")
    sorunlar.append("Model klasoru yolu tespit edilemedi")

# ---------------------------------------------------------------- 2) dosyalar
baslik("2) GGUF DOSYA DOGRULAMASI")
ilk_parca = None
if klasor and os.path.isdir(klasor):
    for ad, beklenen in BEKLENEN_DOSYALAR:
        tam = os.path.join(klasor, ad)
        if not os.path.exists(tam):
            # alt klasorlerde de ara
            for kok, _, dosyalar in os.walk(klasor):
                if ad in dosyalar:
                    tam = os.path.join(kok, ad)
                    break
        if os.path.exists(tam):
            gercek = os.path.getsize(tam)
            if gercek == beklenen:
                durum = "TAM"
            else:
                durum = "BOZUK/EKSIK (beklenen %d bayt)" % beklenen
                sorunlar.append("%s eksik veya bozuk" % ad)
            print("%-52s %12s  %s" % (ad[-52:], gb(gercek), durum))
            if ad.endswith("00001-of-00003.gguf"):
                ilk_parca = tam
        else:
            print("%-52s %12s  BULUNAMADI" % (ad[-52:], "-"))
            sorunlar.append("%s bulunamadi" % ad)
else:
    print("(klasor bulunamadigi icin atlandi)")

# ---------------------------------------------------------------- 3) glibc
baslik("3) GLIBC VE ISLETIM SISTEMI")
print("Kernel   : %s %s" % (platform.system(), platform.release()))
glibc = ""
try:
    glibc = os.confstr("CS_GNU_LIBC_VERSION") or ""
except Exception:
    pass
if not glibc:
    cikti = komut(["ldd", "--version"])
    glibc = cikti.splitlines()[0] if cikti else ""
print("glibc    : %s" % (glibc or "tespit edilemedi"))

glibc_num = None
for parca in glibc.replace("-", " ").split():
    try:
        if parca.count(".") == 1:
            glibc_num = float(parca)
            break
    except ValueError:
        continue

if glibc_num is not None:
    if glibc_num >= 2.35:
        print("-> Hazir 'ubuntu-x64' llama.cpp binary'si CALISIR.")
        notlar.append("Hazir binary indirilebilir (glibc %.2f)" % glibc_num)
    else:
        print("-> UYARI: glibc %.2f < 2.35. Hazir 'ubuntu-x64' binary'si" % glibc_num)
        print("   'GLIBC_2.35 not found' hatasi verir. Kaynaktan DERLEMEK gerekir.")
        notlar.append("Kaynaktan derleme gerekli (glibc %.2f)" % glibc_num)

# ---------------------------------------------------------------- 4) araclar
baslik("4) DERLEME ARACLARI")
for arac, komutlar in [("gcc", ["gcc", "--version"]),
                       ("g++", ["g++", "--version"]),
                       ("cmake", ["cmake", "--version"]),
                       ("make", ["make", "--version"]),
                       ("git", ["git", "--version"]),
                       ("unzip", ["unzip", "-v"])]:
    yol = shutil.which(arac)
    if yol:
        ilk_satir = komut(komutlar).splitlines()
        surum = ilk_satir[0] if ilk_satir else ""
        print("%-8s VAR   %s" % (arac, surum[:60]))
    else:
        print("%-8s YOK" % arac)

if not shutil.which("cmake"):
    print("-> cmake yoksa: pip install --user cmake  (internet varsa) ile kurulabilir")

# ---------------------------------------------------------------- 5) internet
baslik("5) INTERNET ERISIMI (sunucudan)")
try:
    import urllib.request
    for ad, url in [("huggingface.co", "https://huggingface.co/api/models/unsloth/Qwen3.5-122B-A10B-GGUF"),
                    ("github.com", "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"),
                    ("pypi.org", "https://pypi.org/simple/")]:
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                print("%-16s ERISILEBILIR (HTTP %s)" % (ad, r.status))
        except Exception as e:
            print("%-16s erisilemiyor (%s)" % (ad, type(e).__name__))
except Exception as e:
    print("kontrol yapilamadi: %s" % e)
print("(Hepsi kapaliysa llama.cpp'yi kendi PC'nizden indirip yine VERI klasorune")
print(" yuklemeniz gerekir — model dosyalarinda yaptiginiz gibi.)")

# ---------------------------------------------------------------- 6) kaynaklar
baslik("6) SISTEM KAYNAKLARI")
try:
    mem = {}
    with open("/proc/meminfo") as f:
        for satir in f:
            k, _, v = satir.partition(":")
            mem[k.strip()] = v.strip()
    toplam = int(mem["MemTotal"].split()[0]) / 1024.0 ** 2
    bos = int(mem["MemAvailable"].split()[0]) / 1024.0 ** 2
    print("RAM      : %.1f GB toplam / %.1f GB bos" % (toplam, bos))
    gerekli = 71.7 + 4  # agirliklar + KV/calisma payi (32K baglam)
    if bos >= gerekli:
        print("-> Model (71.7 GB) + 32K baglam icin YETERLI (~%.0f GB gerekli)" % gerekli)
    else:
        print("-> DIKKAT: bos RAM %.1f GB, gereken ~%.0f GB. Baglami kucultun (-c 8192)"
              % (bos, gerekli))
        sorunlar.append("Bos RAM sinirda")
except Exception as e:
    print("RAM okunamadi: %s" % e)

print("Cekirdek : %s mantiksal" % (os.cpu_count() or "?"))
if klasor and os.path.isdir(klasor):
    try:
        d = shutil.disk_usage(klasor)
        print("Disk     : %.1f GB bos (%s)" % (d.free / 1024.0 ** 3, klasor))
    except Exception:
        pass

# ---------------------------------------------------------------- 7) llama.cpp
baslik("7) LLAMA.CPP DURUMU")
bulunan = None
for aday in ["llama-server", os.path.expanduser("~/llama.cpp/build/bin/llama-server"),
             os.path.expanduser("~/llama.cpp/llama-server"),
             os.path.expanduser("~/bin/llama-server")]:
    yol = shutil.which(aday) if os.sep not in aday else (aday if os.path.exists(aday) else None)
    if yol:
        bulunan = yol
        break
if bulunan:
    print("llama-server BULUNDU: %s" % bulunan)
else:
    print("llama-server bulunamadi (henuz kurulmadi).")

# ---------------------------------------------------------------- ozet
baslik("SONUC / SONRAKI ADIM")
if sorunlar:
    print("Once cozulmesi gerekenler:")
    for s in sorunlar:
        print("  - %s" % s)
else:
    print("Model dosyalari hazir gorunuyor.")

if bulunan and ilk_parca:
    print("\nHemen deneyebilirsiniz:")
    print("  %s \\" % bulunan)
    print("    -m %s \\" % ilk_parca)
    print("    -c 32768 -t %d --host 127.0.0.1 --port 8080" % max(1, (os.cpu_count() or 8) - 8))
elif ilk_parca:
    print("\nModel yolu (llama.cpp kurulunca -m ile bunu verin):")
    print("  %s" % ilk_parca)
    print("\nllama.cpp icin yol secimi yukaridaki 3. ve 5. bolume gore:")
    print("  glibc >= 2.35 + internet var  -> hazir binary indir (en hizli)")
    print("  glibc <  2.35 + gcc/cmake var -> kaynaktan derle (en uyumlu)")
    print("  internet yok                  -> kaynak/binary'yi PC'den yukle")

if notlar:
    print("\nNotlar:")
    for n in notlar:
        print("  - %s" % n)
