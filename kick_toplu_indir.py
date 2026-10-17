from __future__ import annotations

import argparse
import json
import os
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

# Dosyalar aynı klasördeyse ilk yollar kullanılır.
# "kick api" adlı alt klasöre koyduysan ikinci yollar kullanılır.
CONFIG_ADAYLARI = [
    ANA_KLASOR / "kick-config.js",
    ANA_KLASOR / "kick api" / "kick-config.js",
    ANA_KLASOR / "kick-api" / "kick-config.js",
]

LINK_DOSYASI_ADAYLARI = [
    ANA_KLASOR / "klip.txt",
    ANA_KLASOR / "kick api" / "klip.txt",
    ANA_KLASOR / "kick-api" / "klip.txt",
]

INDIRME_KLASORU = ANA_KLASOR / "indirilen_klipler"
ARSIV_DOSYASI = ANA_KLASOR / "indirilenler.txt"
HATA_DOSYASI = ANA_KLASOR / "basarisiz_klipler.txt"

TOKEN_URL = "https://id.kick.com/oauth/token"
KLIP_API_URL = "https://kick.com/api/v2/clips/{clip_id}/play"

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


def dosya_bul(adaylar: list[Path], aciklama: str) -> Path:
    for yol in adaylar:
        if yol.is_file():
            return yol

    denenmis = "\n".join(f"  - {yol}" for yol in adaylar)
    raise FileNotFoundError(
        f"{aciklama} bulunamadı. Kontrol edilen yollar:\n{denenmis}"
    )


def js_config_oku(config_yolu: Path) -> tuple[str, str]:
    """kick-config.js içindeki CLIENT ID ve CLIENT SECRET değerlerini okur."""
    metin = config_yolu.read_text(encoding="utf-8-sig")

    client_id_eslesme = re.search(
        r"KICK_CLIENT_ID\s*:\s*['\"]([^'\"]+)['\"]", metin
    )
    client_secret_eslesme = re.search(
        r"KICK_CLIENT_SECRET\s*:\s*['\"]([^'\"]+)['\"]", metin
    )

    if not client_id_eslesme or not client_secret_eslesme:
        raise ValueError(
            "kick-config.js içinde KICK_CLIENT_ID veya "
            "KICK_CLIENT_SECRET bulunamadı."
        )

    degerler = client_id_eslesme.group(1), client_secret_eslesme.group(1)
    if any(deger.startswith("YOUR_") for deger in degerler):
        raise ValueError("Örnek ayarları kendi Kick Client ID ve Client Secret bilgilerinle doldur.")
    return degerler


def kimlik_bilgileri(config_yolu: Path | None = None) -> tuple[str, str]:
    client_id = os.environ.get("KICK_CLIENT_ID", "").strip()
    client_secret = os.environ.get("KICK_CLIENT_SECRET", "").strip()
    if client_id or client_secret:
        if not client_id or not client_secret:
            raise ValueError("KICK_CLIENT_ID ve KICK_CLIENT_SECRET birlikte tanımlanmalı.")
        if client_id.startswith("YOUR_") or client_secret.startswith("YOUR_"):
            raise ValueError("Örnek ortam değişkenlerini kendi bilgilerinle doldur.")
        return client_id, client_secret
    return js_config_oku(config_yolu or dosya_bul(CONFIG_ADAYLARI, "kick-config.js"))


def app_token_al(client_id: str, client_secret: str) -> str:
    """Kick OAuth client_credentials akışıyla uygulama tokenı alır."""
    if curl_requests is None:
        raise RuntimeError(
            'curl_cffi kurulu değil. Terminalde şu komutu çalıştır:\n'
            'py -m pip install -U "yt-dlp[default,curl-cffi]"'
        )

    yanit = curl_requests.post(
        TOKEN_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )

    if yanit.status_code >= 400:
        raise RuntimeError(
            f"Kick API token alınamadı. HTTP {yanit.status_code}: "
            "Client ID/Secret ve Kick geliştirici ayarlarını kontrol et."
        )

    try:
        veri = yanit.json()
    except json.JSONDecodeError as hata:
        raise RuntimeError("Kick token yanıtı JSON değil.") from hata

    token = veri.get("access_token") if isinstance(veri, dict) else None
    if not isinstance(token, str) or not token:
        raise RuntimeError("Kick token yanıtında access_token bulunamadı.")

    return token


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


def guvenli_dosya_adi(metin: str, azami_uzunluk: int = 140) -> str:
    metin = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", metin)
    metin = re.sub(r"\s+", " ", metin).strip().rstrip(". ")
    return (metin or "Kick klibi")[:azami_uzunluk].rstrip(". ")


def klip_bilgisi_al(
    oturum: Any,
    orijinal_link: str,
    clip_id: str,
    app_token: str = "",
) -> dict[str, Any]:
    """
    Kick'in klip oynatma uç noktasından klip bilgisini alır.

    İlk istek public erişim şeklinde yapılır. 401/403 gelirse
    yalnız yapılandırılmış bir app token varsa bir kez tekrar denenir.
    """
    url = KLIP_API_URL.format(clip_id=clip_id)
    temel_basliklar = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://kick.com",
        "Referer": orijinal_link,
    }

    yanit = oturum.get(url, headers=temel_basliklar, timeout=30)

    if yanit.status_code in {401, 403} and app_token:
        yetkili_basliklar = {
            **temel_basliklar,
            "Authorization": f"Bearer {app_token}",
        }
        yanit = oturum.get(url, headers=yetkili_basliklar, timeout=30)

    if yanit.status_code >= 400:
        hata = ErisimDurdu if yanit.status_code in {401, 403, 429} else RuntimeError
        raise hata(f"Klip bilgisi alınamadı. HTTP {yanit.status_code}.")

    try:
        veri = yanit.json()
    except json.JSONDecodeError as hata:
        raise RuntimeError("Klip API yanıtı JSON değil.") from hata

    klip = veri.get("clip") if isinstance(veri, dict) else None
    if not isinstance(klip, dict):
        raise RuntimeError("Klip API yanıtında 'clip' alanı bulunamadı.")

    clip_url = klip.get("clip_url")
    if not isinstance(clip_url, str) or not clip_url:
        raise RuntimeError("Klip API yanıtında clip_url bulunamadı.")
    if not clip_url.startswith("https://"):
        raise RuntimeError("Klip medya adresi HTTPS değil.")

    return klip


def medyayi_indir(
    medya_url: str,
    baslik: str,
    clip_id: str,
    referer: str,
) -> None:
    if yt_dlp is None:
        raise RuntimeError(
            'yt-dlp kurulu değil. Terminalde şu komutu çalıştır:\n'
            'py -m pip install -U "yt-dlp[default,curl-cffi]"'
        )

    temiz_baslik = guvenli_dosya_adi(baslik)
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
    parser.add_argument("--config", type=Path, help="Kendi kick-config.js dosyan")
    modlar = parser.add_mutually_exclusive_group()
    modlar.add_argument("--dry-run", action="store_true", help="Yalnız bağlantıları doğrula; ağa bağlanmaz")
    modlar.add_argument("--check-api", action="store_true", help="Yalnız OAuth bağlantısını kontrol et; tokenı göstermez")
    args = parser.parse_args(argv)
    print("Kick toplu klip indirme programı")

    if not args.dry_run and (curl_requests is None or (yt_dlp is None and not args.check_api)):
        print("\nGerekli paketler eksik.")
        print('VS Code terminalinde şunu çalıştır:')
        print('python -m pip install -r requirements.txt')
        return 1

    try:
        if not args.check_api:
            link_dosyasi = args.links or dosya_bul(LINK_DOSYASI_ADAYLARI, "klip.txt")
            print(f"Link dosyası: {link_dosyasi}")
            linkler = linkleri_oku(link_dosyasi)
            if not linkler:
                print("\nİndirilecek geçerli Kick klibi bulunamadı.")
                return 1
            if args.dry_run:
                print(f"{len(linkler)} farklı geçerli klip; ağ isteği ve indirme yapılmadı.")
                return 0

        app_token = ""
        ayar_var = args.config is not None or any(os.environ.get(key) for key in ("KICK_CLIENT_ID", "KICK_CLIENT_SECRET")) or any(yol.is_file() for yol in CONFIG_ADAYLARI)
        if args.check_api or ayar_var:
            client_id, client_secret = kimlik_bilgileri(args.config)
            print("\nKick OAuth uygulama tokenı alınıyor...")
            app_token = app_token_al(client_id, client_secret)
            print("Kick OAuth bağlantısı başarılı. Klip erişimi ayrıca kontrol edilir.")
        else:
            print("OAuth ayarı yok; kliplerin herkese açık erişimi kullanılacak.")
        if args.check_api:
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
                klip = klip_bilgisi_al(oturum, link, clip_id, app_token)
                medya_url = str(klip["clip_url"])
                baslik = str(klip.get("title") or clip_id)

                print(f"Başlık: {baslik}")
                medyayi_indir(medya_url, baslik, clip_id, link)

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
