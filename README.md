# Kick Clip Downloader

**Kick klip bağlantılarını bir metin dosyasından sırayla indiren Python aracı.**
Tekrar eden bağlantıları ayıklar, tamamlanan indirmeleri kaydeder ve yeniden
çalıştırıldığında kayıtlı klipleri atlar. Hesap bağlama veya anahtar kurulumu istemez.
Windows / Python 3.12 için hazırlanmıştır; kaynak kod olarak paylaşılır.

## 1. Kurulum

[Python 3.12](https://www.python.org/downloads/) ve [Git](https://git-scm.com/downloads)
kuruluysa PowerShell'de:

```powershell
git clone https://github.com/tinitavolkan/kick-clip-downloader.git
cd kick-clip-downloader
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Git kullanmıyorsanız **Code → Download ZIP** seçin, ZIP'i açın ve PowerShell'i
proje klasöründe çalıştırın. Ardından son iki komutu uygulayın.
Sanal ortamı etkinleştirmek gerekmez.

HLS veya ayrı ses/görüntü birleştirme gereken klipler için FFmpeg ve FFprobe'un
PATH'te bulunması gerekir. Doğrudan MP4 indirmesinde bunlar gerekmeyebilir.
[yt-dlp bağımlılıkları](https://github.com/yt-dlp/yt-dlp#dependencies)

## 2. Klip listenizi hazırlayın

```powershell
Copy-Item klip.example.txt klip.txt
notepad klip.txt
```

Örnek bağlantıları silip gerçek kliplerinizi her satıra bir tane ekleyin.
`https://kick.com/kanal/clips/clip_...` ve
`https://kick.com/kanal?clip=clip_...` biçimleri desteklenir.
Boş satırlar ve `#` ile başlayan açıklamalar atlanır.
Program kanalı taramaz; verdiğiniz bağlantıları işler.

## 3. Kontrol edin ve indirin

Listeyi indirme yapmadan, çevrimdışı kontrol edin:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py --dry-run
```

Ardından indirmeyi başlatın:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py
```

Farklı bir liste seçmek için:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py --links "C:\Klipler\listem.txt"
```

| Dosya / klasör | Ne içerir? |
| --- | --- |
| `klip.example.txt` | Gerçek olmayan örnek bağlantılar |
| `klip.txt` | Kendi indirme listeniz |
| `indirilen_klipler/` | İndirilen videolar; klip kimliğiyle adlandırılır |
| `indirilenler.txt` | Tamamlanan kliplerin kimlikleri; tekrar indirmeyi önler |
| `basarisiz_klipler.txt` | Son çalıştırmanın hata özeti |

Kendi listeniz, videolarınız, indirme kayıtları ve hata raporu `.gitignore` ile
Git dışında tutulur. Tamamlanmış, boş olmayan medya dosyası bulunmadan indirme
arşivine kayıt eklenmez. Arşivdeki bir videoyu sildiyseniz yeniden indirmek için
ilgili kimliği `indirilenler.txt` içinden çıkarın.

**Ctrl+C** işlemi durdurur. Yeniden çalıştırınca arşivdeki klipler atlanır;
desteklenen indirmelerde yarım dosyadan devam denenir. Klip bilgisi okunurken
401, 403 veya 429 yanıtı gelirse sıra durur. Diğer hatalı klipler rapora yazılır
ve sıradakine geçilir. Otomatik yeniden başlatma yoktur.

Çıkış kodları: `0` başarılı, `1` hata, `2` yanlış komut, `130` kullanıcı iptali.

## Sorun giderme

| Durum | Kontrol |
| --- | --- |
| `klip.txt` bulunamadı | Örnek listeyi kopyalayın veya `--links` ile dosyayı seçin. |
| Geçerli bağlantı yok | Klip sayfasının bağlantısını kullanın; kanal ana sayfası yeterli değildir. |
| 401 / 403 | Kick erişimi reddediyor; sıra durur. |
| 429 | İstek sınırı; bekleyip daha sonra yeniden başlatın. |
| 404 / klip alanı yok | Klip silinmiş veya sitenin yanıt biçimi değişmiş olabilir. |
| FFmpeg bulunamadı | FFmpeg/FFprobe kurup terminali yeniden açın. |

Site değişiklikleri indirmeyi etkileyebilir. Paket güncellemesini ayrı bir sanal
ortamda deneyebilirsiniz: `python -m pip install --upgrade "yt-dlp[default,curl-cffi]" curl-cffi`.
Bu işlem projedeki sabitlenmiş sürümleri değiştirir.

Klipleri yalnız indirme/kullanma hakkınız olan içerikler için kullanın. Tek bir
klibi elle indirmek için Kick'in kendi indirme düğmesi de vardır.
[Kick klip yardım sayfası](https://help.kick.com/en/articles/7120566-how-to-create-clips-on-kick)

## Geliştirme

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/check_release.py
```

Testler yapay yanıtlarla çalışır; gerçek hesap veya klip gerektirmez.
GitHub Actions Windows ve Ubuntu'da Python 3.12 ile bu kontrolleri çalıştırır.

MIT lisanslıdır. `yt-dlp` ve `curl-cffi` ayrı bağımlılıklardır; kendi lisansları
geçerlidir. Kick ile resmî bağlantısı olmayan bağımsız bir araçtır.

### English

A Python tool that sequentially downloads a supplied list of public Kick clip
URLs, skips archived downloads and reports failures. No account setup is needed.
No personal clip lists, downloaded media or local history are included.
See the Turkish installation and usage guide above.
