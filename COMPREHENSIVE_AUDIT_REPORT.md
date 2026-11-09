# Sophon — Önceki Kapsamlı Denetim (Baz Sürüm)

Bu rapor Functions, Linux sandbox ve Policy deny-overrides güncellemelerinden önceki 92 testlik baz sürüm denetimini belgelemektedir. Daha yeni geliştirmeler ve güncel test sonuçları için `SOPHON_FUNCTIONS_SANDBOX_POLICY_REPORT_20261109.md` dosyasına bakın.

---

# Sophon — Kapsamlı Dil ve Çalışma Zamanı Denetim Raporu

**Tarih:** 9 Kasım 2026
**Sürüm:** Genesis 0.0.1
**Denetlenen çalışma zamanı:** Python 3.13.5
**Kapsam:** `.sph`, `.xaf`, `.svt`, CLI, bileşenler, izin sistemi, dosya sistemi, Observer, Agent ve geriye dönük uyumluluk.

## 1. Yönetici özeti

Sophon kaynak kodu gerçek `.sph`, `.xaf` ve `.svt` dosyaları oluşturularak çalıştırıldı. Testler yalnızca sözdizimi kontrolüyle sınırlı kalmadı; veritabanı kayıtları diske yazıldı ve tekrar okundu, dosyalar oluşturuldu/kopyalandı/taşındı/arşivlendi, Observer snapshot ve log dosyaları üretildi, alt `.sph` programı çalıştırıldı, kullanıcı girdileri simüle edildi ve Agent sağlayıcısı HTTP sınırında taklit edilerek sınandı.

| Kontrol | Sonuç |
|---|---:|
| Önceki regresyon testleri | **51/51 geçti** |
| Yeni gerçek çalışma entegrasyon testleri | **41/41 geçti** |
| Toplam otomatik test | **92/92 geçti** |
| Dokümantasyon kod örnekleri | **50/50 ayrıştırıldı** |
| Kaynakta bulunan hata kodları | **250/250 katalogda** |
| Gerçek dosya senaryoları | **10/10 başarılı** |
| Hata enjeksiyonu / bozuk girdi denemeleri | **112 deneme, 0 yakalanmamış Python istisnası** |

Test edilen kaynakta gerçek hatalar bulundu ve düzeltildi. Bunlar arasında arşiv yoluyla dış dosya sızdırma riski, dosya yolu sınırlarının aşılması, SVT yazımının yarıda kalması, metin birleştirme kurallarındaki uyumsuzluk, hata kodu çakışmaları ve bozuk bileşen bloklarında Python `KeyError` oluşması vardı.

## 2. Test edilen dil yüzeyi

### `.sph` — dil ve çalışma zamanı

- `state`, açık tip bildirimleri, tür denetimi, `multi-state`, listeler ve `null`.
- Sayısal ifade motoru: `+`, `-`, `*`, `/`, `^`, parantez ve `sqrt()`.
- Metin interpolation: `"Merhaba, {name}"`.
- `datetime`: `date`, `time`, gün/ay/yıl, ISO weekday ve timezone.
- `surface`, `ask`, `multi-ask`, `confirmation`, `multi-confirmation`.
- `component`, `form`, `note`, `list`, `table`.
- `observer`, `multi-observer`, harici kaynak gözlemi ve `self-observation`.
- `database` ile `.svt` okuma, yazma, değiştirme ve silme.
- `file`: create, write, append, read, list, delete, mkdir, copy, move, zip ve unzip.
- `execute` ile izin listesindeki alt `.sph` dosyasını kendi XAF politikası altında çalıştırma.
- Agent girdileri, dosya ekleri, çıktı state'i, retry ve token limitleri.

### `.xaf` — politika ve yapılandırma

XAF v2'nin `config`, `agent`, sayısal ID'li `policy`, `access`, `action`, Agent varsayılanları, Observer profilleri, veritabanı ayarları, dosya izinleri ve execute allowlist bölümleri denetlendi. Ayrıca eski ad tabanlı XAF biçiminin geriye dönük okuma uyumluluğu test edildi.

### `.svt` — Sophon Vault

Vault kayıtları gerçek program çalıştırılarak okundu ve değiştirildi. Yinelenen kayıt ID'si, yinelenen alan, hatalı sözdizimi, kayıt sınırı ve atomik yazma senaryoları sınandı.

## 3. Bulunan ve düzeltilen sorunlar

| Bulgu | Düzeltme |
|---|---|
| Bir string içinde `multi-state` kelimesinin geçmesi, gereksiz multi yetkisi kontrolü oluşturabiliyordu. | Çoklu bileşen gereksinimi artık string içeriğine değil gerçek program yapısına göre belirleniyor. |
| `write` ve `append` var olmayan dosyayı örtük biçimde oluşturabiliyordu. | Önce açık `create` işlemi gerekiyor. |
| ZIP içindeki symlink, proje dışındaki dosyanın içeriğini arşive taşıyabilirdi. | ZIP oluşturulmadan önce bütün kaynak ağacı inceleniyor; symlink varsa `F025` veriliyor ve kısmi arşiv bırakılmıyor. |
| ZIP açma sırasında mevcut hedefin üzerine yazma ve ZIP Slip riski vardı. | Var olan hedef reddediliyor; arşiv girdileri çıkarılmadan önce hedef dizin sınırına göre doğrulanıyor. |
| Veritabanı bağlantı yolu proje dışına çözümlenebiliyordu. | Gerçek yol ve symlink çözümlemesi sonrasında proje kökü denetleniyor (`F012`). |
| Observer snapshot/log hedefi dışarı yönlendirilebiliyordu. | Mutlak/üst dizin yolları ve proje dışına çıkan symlink hedefleri reddediliyor (`X116` / `F012`). |
| SVT dosyası güncellenirken işlem yarıda kalırsa önceki veri bozulabilirdi. | Geçici dosyaya yazma, `fsync` ve atomik `os.replace` kullanılıyor; başarısızlıkta önceki dosya korunuyor (`V015`). |
| `database read` sonucu `state` hedefinde doğru tutulmuyordu. | Okunan kayıtlar belirtilen state'e aktarılıyor. |
| Observer profil doğrulaması geçerli metin listesini karakterlere ayırabiliyordu. | String ve satır listesi biçimleri ayrı ele alınıyor; geçerli profil ve otomatik XAF üretimi çalışıyor. |
| `surface` ve bazı bileşenlerde metin `+` ile birleştirilebiliyordu. | Kural tutarlı hale getirildi: `+` sayısal; metin interpolation ile yazılıyor. |
| `S173` gibi hata kodları farklı hata türleri için ortak kullanılıyordu. | Metin birleştirme `S251`, geçersiz surface öğesi `S252`, kapatılmamış liste `S253` kodlarına ayrıldı; `S173` multi-ask anlamında kaldı. |
| Yanlış türde iç içe bloklar `KeyError` gibi ham Python istisnaları üretebiliyordu. | Pair/block biçimleri doğrulanıyor; bileşen içerikleri için `S254`, ilgili alanlarda da bağlama özel Sophon hata kodları ekleniyor. |
| CLI `--help` seçeneğini hata olarak yorumluyordu. | `--help`, `-h`, `help` ve `--version` eklendi. |

### Yeni/ayrıştırılmış hata kodları

- `F025`: ZIP kaynak klasöründe sembolik bağlantı bulundu.
- `S251`: `+` surface/component metnini birleştirmek için kullanılamaz.
- `S252`: Geçersiz surface öğesi.
- `S253`: Surface içindeki liste kapatılmamış.
- `S254`: Bileşen ayarı veya içerik öğesi yanlış pair/block biçiminde yazılmış.

Bütün hata kodları `SYNTAX.md` içinde kataloglandı. Dokümantasyon kontrolü kaynakta bulunan 250 hata kodunun tamamını buldu.

## 4. Gerçek çalıştırma senaryoları

`audit_suite/` altında ayrı `.sph`, `.xaf` ve `.svt` örnekleri bulunur. Şu senaryolar gerçek Sophon runtime üzerinden başarılı oldu:

1. Tipli state, aritmetik, interpolation, multi-state ve datetime.
2. Note/list/table ve form tabanlı kayıt ekranı.
3. Ask, multi-ask, confirmation ve multi-confirmation.
4. Kendi kaynağını izleyen Observer ve multi-observer.
5. Harici `.sph` kaynağını izleme ve self-observation özelliği.
6. SVT read/write/modify/remove ve diske geri yazım.
7. Dosya oluşturma, yazma, ekleme, okuma, listeleme, kopyalama, taşıma, ZIP ve unzip.
8. İzin verilen alt `.sph` dosyasını yürütme.
9. Eski XAF biçimiyle program çalıştırma.
10. Agent çağrısının HTTP istek içeriği, çıktı token limiti, dosya eki, retry ve hata davranışları.

Agent testlerinde OpenRouter HTTP uç noktası **mock** edildi. Gerçek API anahtarı veya canlı ağ çağrısı kullanılmadı. Ayrı parse-only senaryoda anahtarın eksik olması beklenen `A021` hatasını üretti. Dolayısıyla bu rapor gerçek sağlayıcı hesabıyla uçtan uca bağlantının doğrulandığını iddia etmez.

## 5. Hata enjeksiyonu ve uyumluluk

112 girdi denemesi `.sph`, `.xaf`, `.svt` bozuk örneklerini, yanlış türde iç blokları ve geçerli örnek dosyaların kesilmiş öneklerini kapsadı. Sonuç:

- 105 girdi konum ve ipucu taşıyan `SophonError` ile reddedildi.
- 7 girdi parser tarafından kabul edildi. Bunların arasında boş kaynak/config dosyaları ve parse aşamasında geçerli görünen, referans doğrulaması çalışma zamanına bırakılan durumlar vardı.
- **0 yakalanmamış Python istisnası** oluştu.

Ek 16 blok-biçimi denemesinde de Python istisnası oluşmadı. `sophon --help`, `sophon --version` ve `sophon run audit_suite/core.sph` komutları çalıştırıldı.

Geriye dönük uyumluluk için eski XAF policy/Agent biçimi özellikle sınandı ve çalışmaya devam ettiği doğrulandı. File bloğundaki mevcut `id = "..."` etiketi de belgelenmiş bir kullanım olduğu için korunmuştur.

## 6. Performans gözlemi

Bu ölçümler yalnızca mevcut test makinesinde, Python 3.13.5 ile yapılan mikro ölçümlerdir; farklı cihazlar veya gerçek projeler için performans garantisi değildir.

| İşlem | Ölçüm |
|---|---:|
| `core.sph` ayrıştırma, 150 tekrar | medyan **0,687 ms**, p95 **1,060 ms** |
| `core.sph` çalışma, 40 tekrar | medyan **3,734 ms**, p95 **4,470 ms** |
| 5.000 öğeli listeyi ayrıştırma | **10,001 ms** |

Bu ölçümler performans regresyonu için ilk referans noktası olarak kullanılabilir. Henüz farklı cihaz/iş yükleriyle karşılaştırmalı benchmark yapılmadı.

## 7. Hâlâ eksik veya tasarım kararı bekleyen alanlar

Bunlar testlerin başarısız olduğu anlamına gelmez; mevcut çalışma zamanının desteklemediği veya tasarım kararı gerektiren alanlardır.

1. **Control Flow:** `if/else`, döngüler ve hata akışı henüz çalışma zamanında yok. Daha gelişmiş uygulamalar için en önemli dil açığı.
2. **Functions:** Fonksiyon tasarımı dokümante; parser/runtime uygulaması henüz yok.
3. **Multi-Agent:** Tasarımı mevcut; çoklu Agent orkestrasyonu henüz çalışmıyor. Bu nedenle `S250` ile açıkça bildirilir.
4. **Standart kütüphaneler:** `datetime` çalışıyor; `math`, `random`, `system/sys` planlı ama henüz uygulanmış değil.
5. **Container izolasyonu:** Gerçek izolasyon backend'i yok. `security.container = true` çalıştırma sırasında `A035` verir; bunu gerçek sandbox gibi değerlendirmemek gerekir.
6. **Execute command:** Komut kayıt defteri boş. `config.execute.command` şimdilik boş kalmalı; shell komut çalıştırma desteği yok.
7. **Agent sağlayıcısı:** Runtime şu an OpenRouter ile sınırlı. Input token sınırı tam tokenizer yerine UTF-8 boyutundan türetilen yaklaşık bir tahmin kullanıyor; görsel token maliyetini kapsamıyor.
8. **Policy kalıtımı:** V2 access izinleri birleştirilerek devralınıyor; alt policy üst policy'den gelen erişimi daraltamıyor. Least-privilege için açık `deny`/`deny-overrides` semantiği önerilir.
9. **Observer harici kaynakları:** `external = true` kaynak sınıfı düzeyinde izin veriyor. Hassas projelerde dosya yolu bazlı allowlist daha güvenli olur.
10. **SVT sorgulama:** Mevcut Vault temel kayıt işlemlerini karşılıyor; indeks, filtre dili, sıralama, şema/migration ve transaction sistemi henüz gelişmiş bir veritabanı seviyesinde değil.
11. **Boş dosya politikası:** Boş `.sph` ve `.xaf` dosyalarının kabul edilmesi mevcut parser davranışıdır. Bunun hata mı yoksa geçerli boş program/config mi sayılacağı dil standardında kesinleştirilebilir.
12. **Platform matrisi:** Testler bu Linux/Python ortamında yapıldı. Android Termux/ARM64, Windows ve macOS çalışma matrisi ayrıca doğrulanmalı.

## 8. Önerilen geliştirme sırası

1. Control Flow tasarımını ve parser/runtime davranışını kesinleştir: koşul, döngü, break/continue ve hata akışı.
2. Functions tasarımını mevcut input/execute/output modeline göre uygula; scope ve return doğrulaması ekle.
3. Policy için `deny` ve inheritance öncelik kurallarını kesinleştir; path bazlı Observer allowlist ekle.
4. SVT için filtreleme/sıralama/indeks ve transaction semantiğini tasarla.
5. `math`, `random`, `system` standart modüllerini ekle.
6. Container izolasyonu ve ikinci Agent provider desteğini gerçek backend testleriyle geliştir.
7. Linux/Termux/Windows/macOS CI matrisi ve gerçek Agent sağlayıcı entegrasyon testi kur.

## 9. Testleri yeniden çalıştırma

Proje dizininde:

```bash
python3 -m py_compile sophon.py test_regressions.py test_language_integration.py check_docs.py run_audit_corpus.py
python3 test_regressions.py
python3 -m unittest -v test_language_integration.py
python3 check_docs.py
python3 run_audit_corpus.py
./sophon --help
./sophon --version
```

`audit_suite/` gerçek örnek dosyaları; `test_language_integration.py` ayrı özellik ve sınır testlerini; `run_audit_corpus.py` çok dosyalı çalışma senaryolarını içerir.

---

**Sonuç:** Mevcut uygulanan Sophon özellikleri için bu denetim kapsamındaki tüm testler geçti. Bulunan hatalar düzeltildi ve testle sabitlendi. Fonksiyonlar, Control Flow, Multi-Agent, gerçek container izolasyonu ve gelişmiş SVT sorguları ise henüz uygulanmış özellikler değil; bir sonraki geliştirme aşamalarının kapsamı olarak bırakıldı.
