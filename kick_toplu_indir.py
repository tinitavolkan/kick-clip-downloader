from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    from curl_cffi import requests as curl_requests
except ImportError:
    curl_requests = None


ANA_KLASOR = Path(__file__).resolve().parent

INDIRME_KLASORU = ANA_KLASOR / "indirilen_klipler"
ARSIV_DOSYASI = ANA_KLASOR / "indirilenler.txt"
HATA_DOSYASI = ANA_KLASOR / "basarisiz_klipler.txt"

KLIP_OYNATMA_URL = "https://kick.com/api/v2/clips/{clip_id}/play"

def klip_linki(link: str) -> tuple[str, str] | None:
    try:
        url = urlsplit(link)
    except ValueError:
        return None
    if url.scheme not in {"http", "https"} or url.netloc.lower() not in {"kick.com", "www.kick.com"}:
        return None
    path = re.fullmatch(r"/([A-Za-z0-9_-]+)/clips/(clip_[A-Za-z0-9_-]+)/?", url.path)
    if path:
        kanal, clip_id = path.groups()
    else:
        kanal_yolu = re.fullmatch(r"/([A-Za-z0-9_-]+)/?", url.path)
        kimlikler = parse_qs(url.query).get("clip", [])
        if not kanal_yolu or len(kimlikler) != 1 or not re.fullmatch(r"clip_[A-Za-z0-9_-]+", kimlikler[0]):
            return None
        kanal, clip_id = kanal_yolu.group(1), kimlikler[0]
    return f"https://kick.com/{kanal}/clips/{clip_id}", clip_id


class ErisimDurdu(RuntimeError):
    """Yetki veya istek sınırında bütün sırayı durdurur."""


def linkleri_oku(link_dosyasi: Path) -> list[tuple[str, str]]:
    """klip.txt içindeki bağlantıları okur ve (URL, clip_id) döndürür."""
    sonuc: list[tuple[str, str]] = []
    gorulen_idler: set[str] = set()

    for satir_no, ham_satir in enumerate(
        link_dosyasi.read_text(encoding="utf-8-sig").splitlines(), start=1
    ):
        link = ham_satir.strip().strip("\"'")

        if not link or link.startswith("#"):
            continue

        eslesme = klip_linki(link)
        if not eslesme:
            print(f"Geçersiz bağlantı atlandı ({satir_no}. satır): {link}")
            continue

        temiz_link, clip_id = eslesme
        if clip_id in gorulen_idler:
            continue

        gorulen_idler.add(clip_id)
        sonuc.append((temiz_link, clip_id))

    return sonuc


def arsivi_oku() -> set[str]:
    if not ARSIV_DOSYASI.exists():
        return set()

    return {
        satir.strip()
        for satir in ARSIV_DOSYASI.read_text(encoding="utf-8-sig").splitlines()
        if satir.strip()
    }


def arsive_ekle(clip_id: str) -> None:
    with ARSIV_DOSYASI.open("a", encoding="utf-8") as dosya:
        dosya.write(f"{clip_id}\n")


def klip_bilgisi_al(
    oturum: Any,
    orijinal_link: str,
    clip_id: str,
) -> dict[str, Any]:
    """Herkese açık klibin medya bilgisini okur."""
    url = KLIP_OYNATMA_URL.format(clip_id=clip_id)
    temel_basliklar = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://kick.com",
        "Referer": orijinal_link,
    }

    yanit = oturum.get(url, headers=temel_basliklar, timeout=30)

    if yanit.status_code >= 400:
        hata = ErisimDurdu if yanit.status_code in {401, 403, 429} else RuntimeError
        raise hata(f"Klip bilgisi alınamadı. HTTP {yanit.status_code}.")

    try:
        veri = yanit.json()
    except json.JSONDecodeError as hata:
        raise RuntimeError("Klip yanıtı JSON değil.") from hata

    klip = veri.get("clip") if isinstance(veri, dict) else None
    if not isinstance(klip, dict):
        raise RuntimeError("Klip yanıtında 'clip' alanı bulunamadı.")

    clip_url = klip.get("clip_url")
    if not isinstance(clip_url, str) or not clip_url:
        raise RuntimeError("Klip yanıtında clip_url bulunamadı.")
    if not clip_url.startswith("https://"):
        raise RuntimeError("Klip medya adresi HTTPS değil.")

    return klip


def medyayi_indir(
    medya_url: str,
    clip_id: str,
    referer: str,
) -> None:
    if yt_dlp is None:
        raise RuntimeError(
            'yt-dlp kurulu değil. Terminalde şu komutu çalıştır:\n'
            'py -m pip install -U "yt-dlp[default,curl-cffi]"'
        )

    cikti_sablonu = INDIRME_KLASORU / f"{clip_id}.%(ext)s"

    ayarlar = {
        "format": "bv*+ba/b",
        "outtmpl": str(cikti_sablonu),
        "merge_output_format": "mp4",
        "noplaylist": True,
        "continuedl": True,
        "overwrites": False,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
        "socket_timeout": 30,
        "windowsfilenames": True,
        "http_headers": {
            "Referer": referer,
            "Origin": "https://kick.com",
        },
    }

    with yt_dlp.YoutubeDL(ayarlar) as indirici:
        sonuc_kodu = indirici.download([medya_url])

    if sonuc_kodu != 0:
        raise RuntimeError(f"yt-dlp hata kodu döndürdü: {sonuc_kodu}")
    tamamlananlar = [
        yol for yol in INDIRME_KLASORU.glob(f"{clip_id}.*")
        if yol.is_file() and yol.suffix.lower() in {".mp4", ".webm", ".mkv", ".mov"}
        and yol.stat().st_size > 0
    ]
    if not tamamlananlar:
        raise RuntimeError("İndirme tamamlanmış medya dosyası üretmedi; arşive eklenmedi.")


def ana_program(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Kick klip bağlantılarını sırayla indirir.")
    parser.add_argument("--links", type=Path, help="Bağlantı listesi (varsayılan: klip.txt)")
    parser.add_argument("--dry-run", action="store_true", help="Yalnız bağlantıları doğrula; ağa bağlanmaz")
    args = parser.parse_args(argv)
    print("Kick toplu klip indirme programı")

    if not args.dry_run and (curl_requests is None or yt_dlp is None):
        print("\nGerekli paketler eksik.")
        print('VS Code terminalinde şunu çalıştır:')
        print('python -m pip install -r requirements.txt')
        return 1

    try:
        link_dosyasi = args.links or ANA_KLASOR / "klip.txt"
        print(f"Link dosyası: {link_dosyasi}")
        linkler = linkleri_oku(link_dosyasi)
        if not linkler:
            print("\nİndirilecek geçerli Kick klibi bulunamadı.")
            return 1
        if args.dry_run:
            print(f"{len(linkler)} farklı geçerli klip; ağ isteği ve indirme yapılmadı.")
            return 0

        print(f"İndirme klasörü: {INDIRME_KLASORU}")

        INDIRME_KLASORU.mkdir(parents=True, exist_ok=True)
        indirilenler = arsivi_oku()
        basarisizlar: list[str] = []

        oturum = curl_requests.Session(impersonate="chrome")

        print(f"\n{len(linkler)} adet farklı klip bulundu.")

        for sira, (link, clip_id) in enumerate(linkler, start=1):
            print("\n" + "=" * 72)
            print(f"{sira}/{len(linkler)} - {clip_id}")
            print(link)
            print("=" * 72)

            if clip_id in indirilenler:
                print("Bu klip daha önce indirildi, atlanıyor.")
                continue

            try:
                klip = klip_bilgisi_al(oturum, link, clip_id)
                medya_url = str(klip["clip_url"])
                baslik = str(klip.get("title") or clip_id)

                print(f"Başlık: {baslik}")
                medyayi_indir(medya_url, clip_id, link)

                arsive_ekle(clip_id)
                indirilenler.add(clip_id)
                print("İndirme tamamlandı.")

            except KeyboardInterrupt:
                print("\nİşlem kullanıcı tarafından durduruldu.")
                return 130

            except ErisimDurdu as hata:
                basarisizlar.append(f"{link}\nHata: {hata}")
                print(f"Sıra durduruldu: {hata} Sonraki klibe geçilmiyor.")
                break

            except Exception as hata:
                hata_metni = f"{link}\nHata: {type(hata).__name__}: {hata}"
                basarisizlar.append(hata_metni)
                print(f"İndirme başarısız: {hata}")

        if basarisizlar:
            HATA_DOSYASI.write_text(
                ("\n" + "-" * 72 + "\n").join(basarisizlar),
                encoding="utf-8",
            )
            print(f"\nBaşarısız bağlantılar: {HATA_DOSYASI}")
        elif HATA_DOSYASI.exists():
            HATA_DOSYASI.unlink()

        print("\nİşlem tamamlandı.")
        return 0 if not basarisizlar else 1

    except KeyboardInterrupt:
        print("\nİşlem kullanıcı tarafından durduruldu.")
        return 130
    except Exception as hata:
        print(f"\nPROGRAM HATASI: {type(hata).__name__}: {hata}")
        return 1


if __name__ == "__main__":
    raise SystemExit(ana_program())
