# Kick Clip Downloader

**Kick klip bağlantılarını bir metin dosyasından sırayla indiren Python aracı.**
Tekrar eden bağlantıları ayıklar, tamamlanan indirmeleri kaydeder ve yeniden
çalıştırıldığında kayıtlı klipleri atlar. Windows / Python 3.12 için hazırlanmıştır.
Kaynak kod projesidir; EXE veya kurulum paketi içermez.

## Nasıl çalışır, Kick API gerekli mi?

Bu sürüm iki ayrı bağlantı kullanır:

| İşlem | Adres | Durum |
| --- | --- | --- |
| Uygulama tokenı alma | `https://id.kick.com/oauth/token` | Resmî Kick OAuth, `client_credentials` akışı |
| Klip medya adresini bulma | `https://kick.com/api/v2/clips/{clip_id}/play` | Kick web sitesinin uç noktası; resmî Public API sözleşmesi değildir |
| Medyayı indirme | Yanıttaki HTTPS medya adresi | `yt-dlp` ile indirme |

**API anahtarı olmadan başlayabilirsiniz.** Program klip bilgisini önce herkese
açık istekle okur. Kendi **Client ID + Client Secret** bilgilerinizi yapılandırırsanız
başlangıçta bir uygulama tokenı alır; 401/403 durumunda isteği tokenla bir kez dener.
OAuth kurulumu isteğe bağlıdır. Tokenın bu
web uç noktasında kabul edileceği garanti değildir; OAuth bağlantısının başarılı
olması klip indirmesinin çalıştığını kanıtlamaz.

17 Ekim 2026 kontrolünde resmî API şemasında klip indirme uç noktası bulunmuyordu.
`yt-dlp`nin Kick klip çıkarıcısı da web sitesinin `/api/v2/clips/.../play` yolunu
kullanıyor. Site değişiklikleri bu aracı etkileyebilir.
[Resmî API şeması](https://api.kick.com/swagger/doc.json) ·
[yt-dlp Kick kaynak kodu](https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/kick.py)

## 1. Python ve bağımlılıkları kurun

[Python 3.12](https://www.python.org/downloads/) ve [Git](https://git-scm.com/downloads)
kuruluysa PowerShell'de:

```powershell
git clone https://github.com/tinitavolkan/kick-clip-downloader.git
cd kick-clip-downloader
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Git kullanmıyorsanız GitHub'da **Code → Download ZIP** seçin, ZIP'i açın ve
PowerShell'i açılmış proje klasöründe çalıştırın. Ardından son iki komutu uygulayın.
Sanal ortamı etkinleştirmek gerekmez.

HLS veya ayrı ses/görüntü birleştirme gereken klipler için FFmpeg ve FFprobe'un
PATH'te bulunması gerekir. Doğrudan MP4 indirmesinde bunlar gerekmeyebilir.
[yt-dlp bağımlılıkları](https://github.com/yt-dlp/yt-dlp#dependencies)

## 2. İsteğe bağlı: kendi Kick API bilgilerinizi alın

Yalnız klip indirmek için önce 4. adıma geçip anahtarsız erişimi deneyebilirsiniz.
OAuth bağlantısını da kurmak istiyorsanız aşağıdaki adımları izleyin.

1. Kendi Kick hesabınızla giriş yapın.
2. Hesap ayarlarından **iki aşamalı doğrulamayı (2FA)** etkinleştirin.
3. **Settings / Ayarlar → Developer / Geliştirici** bölümünü açın.
4. Yeni bir uygulama oluşturun; örneğin `My Clip Downloader` adını verin.
5. Formun istediği uygulama bilgilerini doldurun. Redirect URL zorunluysa
   yerel bir örnek olarak `http://localhost/auth/callback` kullanabilirsiniz.
   Bu betiğin `client_credentials` isteğinde redirect URL kullanılmaz; callback
   sunucusu açmanız veya kullanıcı izin ekranı çalıştırmanız gerekmez.
6. Uygulamanın **Client ID** ve **Client Secret** değerlerini kendi bilgisayarınıza alın.
   Kick parolanızı veya tarayıcı çerezlerinizi programa vermeyin.

Menü adları değişebilir; güncel adımlar için
[Kick App Setup](https://docs.kick.com/getting-started/kick-apps-setup) belgesini izleyin.
Token türü ve gerekli alanlar
[Kick OAuth belgesinde](https://docs.kick.com/getting-started/generating-tokens-oauth2-flow#app-access-token-endpoint)
açıklanır. Bu uygulama tokenı için kullanıcı hesabınıza ait moderasyon/paylaşım
izinleri istemez.

## 3. İsteğe bağlı: API bilgilerini programa tanıtın

```powershell
Copy-Item kick-config.example.js kick-config.js
notepad kick-config.js
```

`YOUR_CLIENT_ID` ve `YOUR_CLIENT_SECRET` alanlarını kendi değerlerinizle değiştirip
kaydedin. Gerçek dosyanın adı **`kick-config.js`** olmalı; örnek dosyayı değiştirmeyin.

| Dosya | İçeriği | GitHub'a gönderilir mi? |
| --- | --- | --- |
| `kick-config.example.js` | Boş ayar şablonu | Evet |
| `kick-config.js` | Size ait uygulama bilgileri | Hayır, `.gitignore` dışında tutar |
| `klip.example.txt` | Gerçek olmayan bağlantı örnekleri | Evet |
| `klip.txt` | Kendi indirme listeniz | Hayır |

Alternatif olarak `KICK_CLIENT_ID` ve `KICK_CLIENT_SECRET` ortam değişkenlerini
tanımlayabilirsiniz. İkisi birlikte tanımlanmalıdır; varsa dosyaya göre önceliklidir.
Secret değerini komut satırı argümanı olarak kabul eden seçenek yoktur.

OAuth bağlantısını **tokenı ekrana yazmadan** kontrol edin:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py --check-api
```

Bu komut sadece token alma işlemini sınar; klip indirmez, tokenı diske kaydetmez.

## 4. Klip listenizi hazırlayın ve indirin

```powershell
Copy-Item klip.example.txt klip.txt
notepad klip.txt
```

Örnek bağlantıları silip gerçek kliplerinizi her satıra bir tane ekleyin.
`/kanal/clips/clip_...` ve `/kanal?clip=clip_...` biçimleri desteklenir.
Boş satırlar ve `#` ile başlayan açıklamalar atlanır. Bu araç kanalı tarayıp bütün
klipleri bulmaz; verdiğiniz bağlantıları işler.

Önce listeyi çevrimdışı kontrol edin; bu adım API bilgisi de istemez:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py --dry-run
```

Ardından indirin:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py
```

Başka bir liste/ayar dosyası seçmek için:

```powershell
.\.venv\Scripts\python.exe kick_toplu_indir.py --links "C:\Klipler\listem.txt" --config "C:\Ayarlar\kick-config.js"
```

- Videolar: proje içindeki **`indirilen_klipler/`**, klip kimliğiyle adlandırılır.
- Tamamlananlar: **`indirilenler.txt`**. Yalnız tamamlanmış, boş olmayan medya
  dosyası bulunduğunda kayıt eklenir.
- Hatalar: **`basarisiz_klipler.txt`**. Dosya o çalıştırmanın hata özetidir;
  her çalıştırma için kalıcı geçmiş değildir.
- **Ctrl+C** işlemi durdurur. Sonraki çalıştırmada arşivdeki klipler atlanır;
  desteklenen indirmelerde yarım dosyadan devam denenir.
- Klip bilgisinde son 401/403 veya 429 yanıtında sıra durur. Diğer hatalı klipler
  kaydedilir ve sıradakine geçilir. Otomatik yeniden başlatma yoktur.
- Çıkış kodları: `0` başarılı, `1` hata/eksik ayar, `2` yanlış komut, `130` kullanıcı iptali.

## Sorun giderme

| Durum | Kontrol |
| --- | --- |
| Örnek ayar uyarısı | `kick-config.js` içindeki `YOUR_...` alanlarını doldurun. |
| OAuth 400/401 | Kendi uygulamanızın Client ID/Secret değerlerini ve geliştirici durumunu kontrol edin. |
| Klip 403 | Web uç noktası erişimi reddediyor olabilir. Token bunu garanti olarak çözmez; sıra durur. |
| 429 | İstek sınırı; bekleyin. Program kendiliğinden yeniden başlamaz. |
| 404 / klip alanı yok | Klip silinmiş veya Kick yanıt biçimi değişmiş olabilir. |
| FFmpeg bulunamadı | FFmpeg/FFprobe kurup terminali yeniden açın. |
| Arşivde var ama video silinmiş | Tekrar indirmek için ilgili kimliği `indirilenler.txt` içinden çıkarın. |

İndirme sorununda paket güncellemesini ayrı bir sanal ortamda deneyebilirsiniz:
`python -m pip install --upgrade "yt-dlp[default,curl-cffi]" curl-cffi`.
Bu işlem sabitlenmiş sürümleri değiştirir. Sorun bildirirken Secret, token,
çerez, gerçek ayar dosyası veya özel bağlantılar göndermeyin.

Klipleri yalnız indirme/kullanma hakkınız olan içerikler için kullanın. Tek bir
klibi elle indirmek için Kick'in kendi indirme düğmesi de vardır.
[Kick klip yardım sayfası](https://help.kick.com/en/articles/7120566-how-to-create-clips-on-kick)

## Geliştirme

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe tools/check_release.py
```

Testler yapay yanıtlarla çalışır; hesap, API anahtarı veya gerçek klip gerektirmez.
GitHub Actions Windows ve Ubuntu'da Python 3.12 ile bu kontrolleri çalıştırır.
Gerçek Kick erişimi; ağınıza, uygulama bilgilerinize ve sitenin güncel davranışına bağlıdır.

17 Ekim 2026'da yerelde bir herkese açık klibin medya bilgisi HTTP 200 ile alındı
ve yaklaşık 49 MiB medya dosyası indirildi. Bu denemede API anahtarı kullanılmadı;
gerçek Client ID/Secret ile OAuth kontrolü yapılmadı. Deneme videosu depoya dahil edilmez.

MIT lisanslıdır. `yt-dlp` ve `curl-cffi` ayrı bağımlılıklardır; kendi lisansları geçerlidir.
Kick ile resmî bağlantısı olmayan bağımsız bir araçtır.

### English

A Python source project for sequentially downloading a supplied list of Kick clip
URLs, skipping archived downloads and reporting failures. Public clip access works
without API credentials where available; optional OAuth uses your own Kick app.
OAuth is official; clip playback uses a website endpoint
outside the documented Public API. No credentials, cookies, real clip lists or
downloaded media are included. See the Turkish setup guide above.
