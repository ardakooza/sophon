<p align="center">
  <img src="assets/sophon-banner.png" alt="sophon logo" width="620" />
</p>

<h1 align="center">Sophon Genesis 0.0.1</h1>

<p align="center">
  Policy-driven language and runtime for `.sph`, `.xaf`, and `.svt` files.
</p>

Sophon, `.sph` kaynak dosyaları, `.xaf` politika dosyaları ve `.svt` veri
dosyalarıyla çalışan küçük, politikaya bağlı bir dil ve çalışma zamanıdır.

**Bu README bir giriş belgesidir.** Tüm blokların tüm argümanları, şemaları,
çalışma zamanı kuralları ve hata kodlarının tamamı
**[`SYNTAX.md`](SYNTAX.md)** içindedir.

```bash
sophon --help
sophon --version
sophon run program.sph
sophon agent -f program.sph -m "Selam."
sophon agent -f program.sph -t "Görev bir"
```

## İlk program

XAF politikası gerektiren özellikleri kullanan program bir XAF'a bağlanır. XAF dosyası ilk
çalıştırmada kendiliğinden oluşturulabilir; mevcut elle yazılmış politika korunur.

```bash
mkdir -p proje && cd proje
cat > merhaba.sph <<'SPH'
connect to merhaba.xaf
state ad = "Dunya"
state greeting = "Merhaba, {ad}"
surface { greeting }
SPH
sophon run merhaba.sph
```

```text
Merhaba, Dunya
```

**Bir XAF birden fazla SPH programı tarafından kullanılabilir.** `config.default-policy`
Agent bağlamayan programlar için varsayılan politikayı seçer. Aynı XAF'ı kullanan
programların ihtiyaç duyduğu izinlerin bu politikada bulunduğundan emin olun.

Launcher çalıştırılabilir olmalıdır. Paylaşımlı depodan kopyalama izin bitlerini
düşürür:

```bash
chmod +x sophon sophon.py
```

---

## Dilin omurgası

Sophon'da 24 deyim vardır ve hepsi [`SYNTAX.md`](SYNTAX.md) bölüm 5'te
listelenmiştir. En çok kullanılanlar:

| Deyim | Rol |
|---|---|
| `state` / `multi-state` | Durum bildirimi |
| `surface` | Konsola çıktı |
| `ask` / `confirmation` | Kullanıcıdan girdi |
| `observer` / `multi-observer` | İç ve dış kaynak gözlemi |
| `database` | Sophon Vault okuma/yazma |
| `file` | Dosya sistemi işlemleri |
| `execute` | Alt program veya komut çalıştırma |
| `agent` | Ajan çağrısı |
| `function` | Tipli parametre, yerel kapsam ve tekli/çoklu dönüşlü fonksiyon |
| `component` | Terminal kutuları |

`state`, `multi-state`, `surface`, `ask`, `multi-ask`, `confirmation`,
`multi-confirmation`, `connect` ve `function` **çekirdektir**, `use` gerektirmez.
Geri kalan modüller içe aktarılmalıdır:

```sph
use { database observer multi-observer agent }
use { component }              // component'in tüm kutu türleri
use { list from component }    // yalnızca liste kutusu
```

## Fonksiyonlar

Fonksiyonlar `function { id input execute output }` ile tanımlanır. Parametreler
tipli olabilir, default veya optional değer alabilir. Tekli ve çoklu dönüş desteklenir.
Ayrıntılar [`FUNCTIONS_DESIGN.md`](FUNCTIONS_DESIGN.md) içindedir.

Control Flow henüz parser/runtime'a uygulanmamıştır. Tasarımda `decide / when / otherwise`
koşul blokları, `not/and/or`, `!=`/`≠`, `>=`/`≥`, `<=`/`≤` ve açık `set` güncellemesi
kullanılır. Ayrıntılar [`CONTROL_FLOW_DESIGN.md`](CONTROL_FLOW_DESIGN.md) içindedir.

Agent sandbox mimarisi, Linux gereksinimleri ve güvenlik sınırları [`SANDBOX.md`](SANDBOX.md) içinde açıklanır.
Son Functions/Sandbox/Policy uygulama ve test sonuçları [`SOPHON_FUNCTIONS_SANDBOX_POLICY_REPORT_20261109.md`](SOPHON_FUNCTIONS_SANDBOX_POLICY_REPORT_20261109.md) içindedir.

## Blok yerleşimi

Bir blok tek satıra da birkaç satıra da yazılabilir; iki biçim tamamen aynıdır.

```sph
multi-state {
    id = "user"
    state {
        ad = "Arda"
        yas = 31
    }
}

multi-state {
    id = "user"
    state { yas = 32 }
}
```

## Yorumlar

`//` tek yorum biçimidir ve satır sonuna kadar geçerlidir.

**Yorum her yerde kabul edilmez.** `//` satırları standart statement parser'larında işlenir; ancak bazı bloklar özel ham içerik ayrıştırıcısı kullanır. Bu nedenle yorumların davranışı bloğa göre değişir:

| Blok | Yorum satırı davranışı |
|---|---|
| `surface` | İçerik öğesi gibi yorumlanır ve `S252` verebilir. |
| `ask` | Geçersiz ayar olarak `S167` verir. |
| `choice` | Geçersiz seçenek girdisi olarak `S180` verir. |
| `note`, `list`, `table`, `form` | Kendi içerik satırı kurallarına göre yorum satırlarını görmezden gelir. |

Yorumu en güvenli şekilde özel içerik bloklarının dışına koyun.

## İfadeler ve metin interpolation

Expression Engine sayısal `+`, `-`, `*`, `/`, `^` ve `sqrt()` işlemlerini destekler.
String birleştirme için `+` kullanılmaz; metin içinde `{state_name}` kullanılır.

```sph
state a = 1
state b = 2
state total = a + b
state name = "Dunya"
state greeting = "Merhaba, {name}"
surface { total greeting }
```

Metin birleştirmede `+` kullanılmaz. `surface`, `note`, `list` ve `table`
metninde de eski `+` birleştirme biçimi reddedilir (`S251`). Sayısal işlemi önce
bir state'e atayın; metin içine değer eklemek için `{state_name}` kullanın.

Liste değerleri köşeli parantezle yazılır, virgül isteğe bağlıdır ve tırnaksız
sözcük **sabit metindir**:

```sph
state secim   = [gece aylik]     // [gece, aylik]
state sayilar = [1 2, 3]
state bos     = []
```

## Çalışma zamanı sırası

```text
agents → databases → file → execute → ask → surface → observers
```

**En önemli ayrım:** en üst düzeyde **önce bütün `ask`'ler sorulur**, sonra
bütün `surface` blokları çizilir. Bu yüzden en üst düzeyde `surface` ile `ask`'in
kaynak sırası önemsizdir. Ama bir `form` **içinde** adımlar tek tek kaynak
sırasına göre çalışır ve bir `surface` satırı, dolduran `ask`'ten önce gelirse
`S102` alır.

```sph
// En üst düzey: sorun yok.
surface { ad }
ask { id = "a1" prompt = "Adınız:" state = ad }

// Form içi: HATA (S102).
form {
    surface { ad }
    ask { id = "a1" prompt = "Adınız:" state = ad }
}
```

## Tam SPH/XAF referansı

Bütün uygulanmış SPH deyimlerinin ve iç içe bileşenlerinin referansı için
[`SPH_XAF_COMPLETE_REFERENCE.md`](SPH_XAF_COMPLETE_REFERENCE.md) dosyasına bakın.
Güncel XAF v2 şeması için [`XAF_V2_SCHEMA.md`](XAF_V2_SCHEMA.md) esas alınmalıdır.

## Yerel standart kütüphane: `datetime`

`datetime`, XAF izni gerektirmeyen yerel standart kütüphanedir ve açıkça içe aktarılır:

```sph
use { datetime }

state today = date
state current_time = time
state day = date.day
state month = date.month
state year = date.year
state weekday = date.weekday
state timezone = date.timezone
state hour = time.hour
state minute = time.minute
state second = time.second
```

| Yerleşik değer | Tip | Anlam |
|---|---|---|
| `date` | string | Yerel tarih, `YYYY-MM-DD` |
| `date.day` | integer | Ayın günü, `1..31` |
| `date.month` | integer | Ay, `1..12` |
| `date.year` | integer | Yıl |
| `date.weekday` | integer | ISO 8601 haftanın günü: Pazartesi `1`, Pazar `7` |
| `date.timezone` | string | Yerel IANA saat dilimi adı; bulunamazsa sistemin saat dilimi kısaltması/ofseti |
| `time` | string | Yerel saat, `HH:MM:SS` |
| `time.hour` | integer | Saat, `0..23` |
| `time.minute` | integer | Dakika, `0..59` |
| `time.second` | integer | Saniye, `0..59` |

Tarih ve saat, program ayrıştırılırken tek bir yerel zaman anından alınır; böylece bütün alanlar birbiriyle tutarlıdır. `date` ve `time` adları datetime modülü yüklendiğinde ayrılmış yerleşik adlardır.

`surface` içinde de doğrudan kullanılabilir:

```sph
surface {
    date
    time
    date.weekday
    date.timezone
}
```

## XAF kontrol katmanı

XAF v2, sistem ayarlarını tek `config {}` bloğunda; Agent kayıtlarını `agent {}`
bloklarında; erişim ve işlem izinlerini sayısal kimlikli `policy {}` bloklarında
tutar. `access` kaynak yeteneğini, `action` yapılabilecek işlemi belirler.

```xaf
config {
    default-policy = 2001
    agent {
        permission { execute = true }
        timing { delay = 60 timeout = 180 }
        input { max-token = 12000 }
        output { max-token = 4096 }
        connection { provider = "openrouter" model = "provider/model-id" key = "OPENROUTER_API_KEY" }
    }
}

agent { id = 1001 name = "Research Agent" policy = 2001 }

policy {
    id = 2001
    access { agent multi observer }
    action { read = true write = true }
}
```

Tam, zorunlu/opsiyonel alanları ve çalışma zamanı davranışlarını içeren şema:
[`XAF_V2_SCHEMA.md`](XAF_V2_SCHEMA.md).
Eski ad tabanlı XAF biçimleri yalnızca geriye dönük uyumluluk için okunur.

## Yerel standart kütüphaneler

Sophon'un yerel standart kütüphane ailesi dört modülden oluşacak:

| Modül | Durum | Amaç |
|---|---|---|
| `math` | Planlandı | Matematiksel fonksiyonlar ve sabitler |
| `datetime` | Uygulandı | Yerel tarih ve saat |
| `system` (`sys`) | Planlandı | Çalışma zamanı ve sistem bilgileri |
| `random` | Uygulandı | Rastgele değerler ve seçimler |

`datetime` ve `random` yerel olarak kullanılabilir. `math` ve `system` (`sys`) sonraki aşamalara bırakılmıştır.

## Modüller

`state`, `multi-state`, `surface`, `ask`, `multi-ask`, `confirmation`,
`multi-confirmation`, `connect` çekirdektir. Kalan her şey içe aktarılmalıdır:

| Modül | Ne açar |
|---|---|
| `database` | `database` bloğu |
| `observer` | Yalnızca `observer` bloğu |
| `multi-observer` | Yalnızca `multi-observer` bloğu |
| `agent` | `agent connect/run/task` |
| `component` | `form`, `note`, `list`, `table` kutuları |
| `file` | `file` bloğu |
| `execute` | `execute` bloğu |
| `datetime` | Yerel tarih ve saat değerleri (`date`, `time`) |
| `random` | Rastgele değer üretimi ve listeden seçim (`random.integer`, `random.float`, `random.boolean`, `random.choice`) |

`datetime` ve `random`, XAF izni gerektirmeyen yerel standart kütüphanelerdir. Diğer modüller mevcut XAF/politika kurallarına tabidir. Bilinmeyen modül `S111`, yinelenen içe aktarma `S112`, kullanılan ama içe aktarılmamış modül `S112`/`S114` verir.

## Gözlem

`observer` hem yerel hem harici kaynakları izler. Her gözlemcinin benzersiz bir
`id`, `source` ve en az bir `watch` bileşeni olmalıdır.

```sph
use { observer }

state level = 12
multi-state { id = "user" state { name = "Arda" age = 18 } }

observer {
    id = "user-watch"
    source = self
    watch {
        user
        user.age
        level
    }
}
```

Harici kaynak için `source = "main.sph"` kullanılır. Birden fazla gözlemci
`multi-observer` içinde gruplanabilir. `observer` ve `multi-observer` ayrı
modüllerdir; grup kullanımı için `use { multi-observer }` gerekir ve ayrıca
`use { observer }` gerekmez. `observe` ve bağımsız `self-observer`
deyimleri kaldırılmıştır. `watch { self-observation }` için kaynak `.sph`
dosyasının bağlı olduğu XAF'ta `features { self-observation = true }` olmalıdır. Ayrıntı:
[`SYNTAX.md` bölüm 16-17](SYNTAX.md#16-observer-ve-multi-observer--birleşik-gözlem-sistemi).

## Dosya ve execute

Her dosya işlemi proje dizini içinde kalır ve `file-system` yetkisi ister. Yeten
iki bağımsız ekseni vardır: dosya ve klasör.

```xaf
policy app.sph {
    access {
        file-system {
            allowed_path { "cikti" "arsiv.zip" }
            forbidden_path { "cikti/private" }
            action {
                file { create read modify }
                folder { create read zip-unzip }
            }
        }
    }
    action { read = true }
}
```

```sph
use { file }

file {
    mkdir { path = "cikti" }
    write { path = "cikti/rapor.txt" data = "hazir" }
    read  { path = "cikti/rapor.txt" state = rapor }
    list  { path = "cikti" state = dosyalar }
    zip   { path = "cikti" to = "arsiv.zip" }
}
surface { rapor }
```

`copy`, `move`, `zip` ve `unzip` için `to` zorunludur. Yollar önce çözülür ve
proje içinde olduğu doğrulanır (`F010`, `F012`), **sonra** politika sorgulanır;
izin verilen bir klasörü adıyla yazmak yol kaçışı sağlayamaz.

`execute.command` **kabuğa asla gitmez**; komutlar iç bir kayıt defterinden
çözülür ve bu defter şu anda boştur, dolayısıyla her komut reddedilir (`X054`).
`execute.file` başka bir programı **kendi politikasıyla** çalıştırır ve derinlik
sınırı 4'tür (`S234`).

Ayrıntı: [`SYNTAX.md` bölüm 21-22](SYNTAX.md#21-file--dosya-işlemleri).


## Yerel standart kütüphane: `random`

`random`, XAF izni gerektirmeyen yerel standart kütüphanedir. Açıkça içe aktarılır:

```sph
use { random }

state dice = random.integer(1, 6)
state probability = random.float()
state enabled = random.boolean()
state color = random.choice(["red", "green", "blue"])
```

| Fonksiyon | Dönüş tipi | Davranış |
|---|---|---|
| `random.integer(min, max)` | integer | İki sınır dahil rastgele tam sayı üretir. |
| `random.float()` | float | `0.0` dahil, `1.0` hariç rastgele sayı üretir. |
| `random.boolean()` | boolean | Rastgele `true` veya `false` üretir. |
| `random.choice(list)` | Listenin eleman tipi | Boş olmayan listeden bir eleman seçer. |

`random.integer` için iki sınır da integer olmalı ve minimum maksimumdan büyük olmamalıdır. `random.choice` boş liste kabul etmez. Her çağrı yeni bir değer üretir; aynı programdaki sonuçlar sabit değildir. Bu üreteç kriptografik değildir; parola, token veya güvenlik anahtarı üretmek için kullanılmamalıdır.

## Bu dağıtımın içeriği

```text
sophon.py       çalışma zamanı
sophon          launcher
AGENT.md        zorunlu ajan çalışma şartnamesi
README.md       bu belge — giriş
SYNTAX.md       söz dizimi ve hata kataloğu
XAF_V2_SCHEMA.md XAF v2 yapılandırma / izin şeması
test_regressions.py regresyon testleri
test_language_integration.py gerçek .sph/.xaf/.svt entegrasyon testleri
run_audit_corpus.py ayrı Sophon programlarından oluşan çalıştırılabilir denetim paketi
audit_suite/    ayrı çalıştırılabilir Sophon test programları ve kaynak dosyaları
check_docs.py   belge kod blokları ve hata kataloğu kapsamını denetler
```

## Hatalar

Kodlar alt sistemlere göre gruplanır ve her biri tek bir koşula karşılık gelir.

| Önek | Alt sistem | Örnek |
|---|---|---|
| `S1xx`, `S2xx` | SPH dili | `S100` bilinmeyen deyim, `S238` çoklu seçim için `requirement` şart |
| `X0xx` | Kontrol düzlemi | `X025` politika yok, `X054` komut yetkisi yok |
| `V0xx` | Sophon Vault | `V005` vault dosyası yok, `V011` geçersiz değer |
| `A0xx` | Ajan | `A012` yürütme reddedildi, `A027` program dosyası yok, `A031` gecikme geçersiz |
| `F0xx` | Dosya sistemi | `F010` mutlak yol, `F012` proje dışı, `F019` dosya yok |
| `O2xx` | Gözlem | `O201` kaynak dosya yok, `O207` self-observation özelliği kapalı |
| `W0xx` | Kurtarılmış koşullar | `W001` okunamayan gözlem günlüğü |

**Hata kodlarının tamamı** [`SYNTAX.md` sonundaki katalogda](SYNTAX.md#hata-ve-uyarı-kataloğu)
listelenmiştir.

Kurtarılmış bir koşul sessizce yutulmaz; okunamayan bir gözlem günlüğü
`.corrupt` ekiyle kenara alınır ve `stderr`'e bildirilir, çalışma sürer:

```text
SophonWarning [W001] Observation log is unreadable (...); its history was not recorded this run.
  --> logs/2026-09-27.json
```

## Notlar

- Bu dağıtımda hazır `.sph`, `.xaf` veya `.svt` örnek projesi **yoktur**. Kendi
  programınızı yazın; XAF bağlantı sırasında otomatik üretilebilir.
- `test_regressions.py` eski davranışları koruyan regresyon testleridir:
  `python3 test_regressions.py`.
- `test_language_integration.py` gerçek dosyalarda çalışma zamanı testleridir:
  `python3 -m unittest -v test_language_integration.py`.
- `check_docs.py`, SYNTAX/XAF örneklerini gerçek parser'dan geçirir ve hata kodu
  kataloğunun tamlığını denetler: `python3 check_docs.py`.
- `run_audit_corpus.py`, `audit_suite/` içindeki ayrı SPH/XAF/SVT programlarını
  çalıştırarak manuel kapsam kontrolü yapar.
- `AGENT.md` isteğe bağlı değildir. Ajan çalıştıran bir program onu bulamazsa
  `A026` ile durur; ajan istemi bu dosyadan kurulur ve çalışma zamanı bir
  şartname uydurmaz.
- `create xaf` ve `create` komutları varsayılan XAF dosyasını oluşturur; `&`
  ile `connect to <dosya>.xaf` komutuyla zincirlenebilir.
- `agent { id = "..." }` biçimi kaldırılmıştır ve `A015` verir; yerine
  `agent connect { id = "..." }` kullanılır.


## Güncel dil çekirdeği: tipler ve ifadeler

`state name: integer = 18` biçiminde açık tip bildirimi ve `state name = 18`
biçiminde tip çıkarımı desteklenir. Aynı state farklı bir değerle tekrar yazılırsa
güncellenir; aynı değer tekrar atanırsa `S246` oluşur. `set name = value` mevcut
state'i açıkça günceller; yeni state oluşturmaz ve türü korur (`S284`, `S289`). Sayısal ifadeler `+ - * / ^`,
parantez ve `sqrt(...)` içerir. Metin içinde `{state_name}` kullanılarak interpolasyon
yapılır; metin birleştirmek için `+` kullanılmaz. Mantıksal işlemler ve karşılaştırmalar
Control Flow'un parser/runtime aşamasında uygulanacaktır; tasarımda `decide / when /
otherwise`, `not/and/or`, `!=`/`≠`, `>=`/`≥` ve `<=`/`≤` bulunur.

Functions parser/runtime tarafından uygulanmıştır. Control Flow tasarımı `decide / when / otherwise` biçiminde kesinleştirilmiştir; parser/runtime uygulaması henüz yapılmamıştır. Tasarım `CONTROL_FLOW_DESIGN.md` içindedir.
