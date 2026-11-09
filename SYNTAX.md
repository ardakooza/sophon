# Sophon — Söz Dizimi Referansı

Bu belge, `sophon.py` içindeki gerçek ayrıştırıcıdan türetilmiştir. Her blok için
zorunlu alanlar, opsiyonel alanlar ve çalışma zamanı kuralları listelenir.

Kural: **bu belgede yazmayan bir şey çalışmaz.** Aksine, burada yazan bir şey de
kaynakta yoksa çalışmaz. Şüphede `sophon.py` kazanır.

## İçindekiler

1. [Dosya biçimleri](#1-dosya-biçimleri)
2. [Yorumlar](#2-yorumlar)
3. [Değerler](#3-değerler)
4. [İfadeler ve birleştirme](#4-ifadeler-ve-birleştirme)
5. [Program anatomisi](#5-program-anatomisi)
6. [Çalışma zamanı sırası](#6-çalışma-zamanı-sırası)
7. [`use` — modül içe aktarma](#7-use--modül-içe-aktarma)
   - [`datetime` — yerel tarih ve saat](#71-datetime--yerel-tarih-ve-saat)
8. [`connect` — XAF bağlantısı](#8-connect--xaf-bağlantısı)
9. [`state` — tek durum](#9-state--tek-durum)
10. [`multi-state` — gruplanmış durum](#10-multi-state--gruplanmış-durum)
11. [`surface` — çıktı](#11-surface--çıktı)
12. [`ask` — soru](#12-ask--soru)
13. [`multi-ask` — soru grupları](#13-multi-ask--soru-grupları)
14. [`confirmation` — seçimli soru](#14-confirmation--seçimli-soru)
15. [`multi-confirmation` — seçim grubu](#15-multi-confirmation--seçim-grubu)
16. [`observer` — gözlemci](#16-observer--gözlemci)
17. [`multi-observer` — gözlemci grubu](#17-multi-observer--gözlemci-grubu)
18. [`features` — XAF özellikleri](#18-xaf-features--özellik-anahtarları)
20. [`component` / `form` / `note` / `list` / `table`](#20-component--form--note--list--table)
21. [`file` — dosya işlemleri](#21-file--dosya-işlemleri)
22. [`execute` — program ve komut çalıştırma](#22-execute--program-ve-komut-çalıştırma)
23. [`database` — Sophon Vault](#23-database--sophon-vault)
24. [`agent` — ajanlar](#24-agent--ajanlar)
   - [Multi-agent taslağı](#24a-multi-agent-tasarım-taslağı)
   - [`function` — fonksiyonlar](#24b-function--fonksiyon-tanımı-ve-çağrısı)
   - [Control Flow taslağı](#24c-control-flow-tasarım-taslağı)
25. [XAF dosyası](#25-xaf-dosyası)
26. [SVT dosyası](#26-svt-dosyası)
27. [CLI](#27-cli)
28. [Hata ve uyarı kataloğu](#hata-ve-uyarı-kataloğu)

---

## 1. Dosya biçimleri

| Uzantı | Ad | Rol |
|---|---|---|
| `.sph` | Sophon programı | Yürütülen kaynak. Politika gerektirir. |
| `.xaf` | Politika/denetim dosyası | Yetkileri tanımlar. **Doğrudan çalıştırılmaz.** |
| `.svt` | Sophon Vault | Veri kaydı. `database` bloğuyla okunur/yazılır. |

Bir `.sph` dosyası bir `.xaf`'a `connect to` ile bağlanır. Bağlantı yoksa program
`X008` ile durur — `connect` olmadan hiçbir şey çalışmaz, `state` ve `surface`
dahil.

> **Çoklu program, tek XAF tuzağı.** Otomatik üretilen politika, adı `.sph`
> dosyasının adına göre oluşturulur. Aynı XAF'a bağlanan ikinci bir program için
> politika üretilmez ve o program `X025` alır. Her program için ayrı XAF kullanın
> ya da politikayı elle genişletin.

## 2. Yorumlar

`//` tek yorum biçimidir ve satır sonuna kadar geçerlidir. `.sph`, `.xaf` ve
`.svt` dosyalarının üçünde de aynıdır.

```sph
// tam satır yorumu
state a = 1   // satır sonu yorumu
```

Boş satırlar ve yalnızca yorum içeren satırlar her blok içinde serbesttir. Dosya
başındaki bayt sırası işareti yok sayılır.

### Yorumun kabul edildiği ve reddedildiği yerler

Bu Sophon'da **kısıtlıdır** ve bu bilinçlidir: yorum birkaç ayrıştırıcının ham
metin taramasına girer ve orada bir sözcük gibi görünür. Aşağıdaki blok
gövdeleri yorum satırını içerik sanar ve reddeder:

| Gövde | Hata | Neden |
|---|---|---|
| `surface { }` | `S170` | Öğeleri ham metin olarak tarar. |
| `note` / `list` / `table` / `form` | `S203` | Kutu gövdesi ham metin olarak taranır. |
| `ask { }` | `S167` | Ayarları konum tabanlı ham tarar. |
| `choice { }` | `S180` | Seçenekleri ham tarar. |

Şu gövdeler yorumu **kabul eder**: `state`, `use`, `multi-state`, `observer`,
`database` işlemleri, `file` işlemleri, `confirmation`, `agent connect/run/task`,
`execute` ve XAF içindeki `policy`, `access`, `action`, `features`, `observer` blokları.

Yani `confirmation` yorum kabul eder ama içindeki `choice` bloğu etmez. Şüphede
yorumu bloğun dışına alın — bu her zaman güvenlidir.

## 3. Değerler

Bir değer şu türlerden biridir:

| Tür | Örnek | Not |
|---|---|---|
| Tamsayı | `17`, `-3` | |
| Ondalık | `3.5`, `-0.5`, `2.` | |
| Metin | `"Arda"` | Tırnak zorunlu. Kaçış `\"` ve `\\` desteklenir. |
| Boolean | `true`, `false` | |
| Null | `null` | |
| Liste | `[a b c]`, `[1 2, 3]`, `[]` | Virgül isteğe bağlı. |
| Durum başvurusu | `ad`, `user.yas` | Yalnızca `surface` ve seçeneklerde. |

Liste ayrıştırma ayrıntıları:

- Virgül isteğe bağlı: `[a b]` ile `[a, b]` aynıdır.
- Boş liste `[]` geçerlidir.
- Tırnaksız bir sözcük **sabit metindir**, durum başvurusu değildir. Bu yüzden
  `[gece aylik]` yazım hatasıyla bir durumla karıştırılamaz.
- Listeler bir değerdir: Vault kaydına ve gözlem anlık görüntüsüne bütün olarak
  gider.
- Boş olmayan her liste öğesi gerekir.

## 4. İfadeler ve metin interpolation

Sayısal Expression Engine şu işlemleri destekler: `+`, `-`, `*`, `/`, `^`, parantez
ve `sqrt(expression)`. `+` burada yalnızca sayısal toplama operatörüdür.

String birleştirme için `+` kullanılmaz. Metin interpolation, `state` değerinde
`{state_name}` ile yapılır:

```sph
state first = 2
state second = 3
state total = first + second
state name = "Arda"
state greeting = "Hello, {name}"
surface { total greeting }
```

Mantıksal işlemler ve karşılaştırmalar henüz desteklenmez.

**Geçiş notu:** Mevcut parser'ın `surface`, component içerikleri ve file `data`
alanlarında kullandığı eski operand tarayıcısı `+` ile literal birleştirmeyi hâlâ
kabul edebilir. Bu legacy davranıştır; hedef Sophon kuralı değildir ve yeni kodda
kullanılmamalıdır. Ayrıca doğrudan `surface` içindeki string literal'lar henüz
runtime interpolation yapmaz; önceden bir `state` içinde hazırlanmış metni
`surface { greeting }` biçiminde gösterin.

## 5. Program anatomisi

Bir `.sph` dosyası sıralı **deyimlerden** oluşur. Tanınan 25 deyim vardır:

```text
use              connect
state            multi-state       surface
ask              multi-ask         confirmation
multi-confirmation                 observer
multi-observer                     database
file             execute           component
form             note              list          table
agent connect    agent run         agent task
function
```

Ayrıştırıcı bu sırayla dener ve **ilk eşleşen dalı alır**. Bu sıra şu sonucu
doğurur:

- `component` bloğu, `form`/`note`/`list`/`table` bloklarından **önce** denenir.
  Bu nedenle `component` bir kutu adı değildir, bir kapsayıcıdır.
- `agent connect` / `agent run` / `agent task`, çıplak `agent { }` denemesinden
  önce gelir.
- Çıplak `agent { }` tamamen kaldırılmıştır ve `A015` verir.

Değişken blok gövdesi **satır tabanlı** ayrıştırılır. Bu nedenle iki sözcükten
oluşan bir anahtar (`multi-state`, `create`, `state =`...) yalnızca o satırda
başladığında geçerlidir.

## 6. Çalışma zamanı sırası

```text
agents → databases → file → execute → ask → surface → observers
```

- `ask`, `surface`'ten önce çalışır; `ask` durum üretir.
- `surface`, gözlemcilerden önce çalışır; gözlem başarısız olsa bile çıktı
  üretilmiş olur.
- Yüzey aşamasında `surface` blokları ve bileşen kutuları **kaynak sırasına**
  göre çizilir; bir formun kendi istemleri tam o anda çalışır.
- `file`, `execute` ve `database` yan yana durur: üçü de program dışı durumu
  okur veya değiştirir, `ask` bunların ürettiğine bağımlı olabilir.

### Kaynak sırası en üst düzeyde etkisizdir, formda etkilidir

Bu, en çok yanlış anlaşılan ayrımdır:

| Bağlam | Davranış |
|---|---|
| **Program en üst düzeyi** | **Önce bütün `ask`'ler sorulur**, sonra bütün `surface` blokları çizilir. Bu yüzden `surface` bir `ask`'ten önce yazılsa da çalışır. |
| **`form` içi** | Adımlar **tek tek, kaynak sırasına göre** çalışır. Bir `surface` satırı, dolduran `ask`'ten önce gelirse `S102` alırsınız. |

```sph
// En üst düzey: bu sıra sorun değildir, çünkü ask önce çalışır.
surface { ad }
ask { id = "a1" prompt = "Adınız:" state = ad }
```

```sph
// Form içi: bu sıra HATADIR, S102 verir.
form {
    surface { ad }                          // ad henüz yok
    ask { id = "a1" prompt = "Adınız:" state = ad }
}
```

Form içinde doğru yol, `surface` satırını `ask`'ten sonra yazmaktır:

```sph
form {
    ask { id = "a1" prompt = "Adınız:" state = ad }
    surface { ad }
}
```

En üst düzeyde `ask`'ler de kendi aralarında kaynak sırasına göre sorulur ve
`surface` blokları da kendi aralarında kaynak sırasına göre çizilir; iki grup
arasındaki sıra önemsizdir.

Gizli (`secret`) alanlar `ask` sonrasında `states` sözlüğünden çıkarılır, bu yüzden
gözlem anlık görüntüsüne ve günlük gözlem günlüğüne düz metin olarak hiç yazılmaz.

---

## 7. `use` — modül içe aktarma

**Çekirdek (import gerekmez):** `state`, `multi-state`, `surface`, `ask`,
`multi-ask`, `confirmation`, `multi-confirmation`, `connect`.

**Modül (import gerekir):** `database`, `observer`, `agent`,
`component`, `file`, `execute`, `datetime`, `random`. `datetime` ve `random` yerel standart kütüphanelerdir; XAF yetkisi gerektirmez.

```sph
use { database observer agent }
use { component }              // component'in tüm kutu türleri
use { list from component }    // yalnızca liste kutusu
use { list from component  file }
```

Kurallar:

- Blok tek satıra da yazılabilir: `use { database }` ile
  `use {
    database
}` aynıdır.
- Modül adı `[A-Za-z_][\w-]*` olmalı; başka bir ad `S111` verir.
- Aynı modülü iki kez içe aktarmak `S112` verir.
- Aynı `ad from modül` çiftini tekrarlamak `S112` verir.

`math`, `system`/`sys` ve `multi-agent` planlanmış modüllerdir; bu çalışma zamanı sürümünde henüz içe aktarılamazlar ve `S250` verirler. `function {}` ise temel dil deyimidir ve uygulanmıştır.
- Boş `use { }` bloğu `S110` verir.
- **Kullanılan modülü içe aktarmamak hatadır** (`_require_module`); örneğin
  `use { }` yazılmadan `database` bloğu kullanmak reddedilir.
- Bir kutu türünü kullanmak için `component` ya da o türün kendisi (`form`,
  `note`, `list`, `table`) içe aktarılmış olmalıdır; aksi hâlde `S114`.

## 7.1. `datetime` — yerel tarih ve saat

`datetime` ve `random`, XAF izni gerektirmeyen yerel standart kütüphanelerdir. Tarih/saat değerleri için `use { datetime }`, rastgele değerler için `use { random }` gerekir. `date` ve `time` yerleşik değerleri program ayrıştırılırken aynı yerel zaman anından üretilir.

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

| Değer | Tip | Açıklama |
|---|---|---|
| `date` | string | `YYYY-MM-DD` yerel tarih |
| `date.day` | integer | Ayın günü (`1..31`) |
| `date.month` | integer | Ay (`1..12`) |
| `date.year` | integer | Yıl |
| `date.weekday` | integer | ISO 8601: Pazartesi `1` … Pazar `7` |
| `date.timezone` | string | Yerel IANA saat dilimi; yoksa sistemin kısaltması/ofseti |
| `time` | string | `HH:MM:SS` yerel saat |
| `time.hour` | integer | Saat (`0..23`) |
| `time.minute` | integer | Dakika (`0..59`) |
| `time.second` | integer | Saniye (`0..59`) |

`date` ve `time` isimleri modül yüklendiğinde ayrılmıştır. Bunlar state olarak yeniden tanımlanamaz. `datetime` yerel bir kütüphane olduğundan tek başına XAF bağlantısı veya XAF yetkisi gerektirmez. `surface` kullanımı ise mevcut yüzey yetkilendirme kurallarına tabidir.

```sph
connect to app.xaf
use { datetime }
state today = date
surface { today date.weekday date.timezone time }
```

## 7.2. `random` — rastgele değerler

`random`, XAF izni gerektirmeyen yerel standart kütüphanedir. Kullanmak için `use { random }` gerekir.

```sph
use { random }
state dice = random.integer(1, 6)
state probability = random.float()
state enabled = random.boolean()
state color = random.choice(["red", "green", "blue"])
```

| Fonksiyon | Dönüş | Açıklama |
|---|---|---|
| `random.integer(min, max)` | integer | Dahilî alt ve üst sınırlar arasında tam sayı. |
| `random.float()` | float | `0.0 <= value < 1.0`. |
| `random.boolean()` | boolean | Rastgele `true` veya `false`. |
| `random.choice(list)` | Eleman türü | Boş olmayan listeden rastgele eleman. |

Modül adı `random` ayrılmıştır. Fonksiyonlar yalnızca modül içe aktarıldığında kullanılabilir. `random.integer` iki integer argüman ister; minimum maksimumdan büyük olamaz. `random.choice` tek ve boş olmayan liste ister. Üreteç kriptografik değildir; güvenlik anahtarı, parola veya token üretmek için kullanılmamalıdır.

## 8. `connect` — XAF bağlantısı

```sph
connect to sophon.xaf
```

- Tam sözdizimi tek satır: `connect to <ad>.xaf`.
- Hedef `[A-Za-z0-9_./-]+\.xaf` ile eşleşmelidir, aksi hâlde `X002`.
- Dosya başına **yalnızca bir** `connect` olabilir; ikincisi `X001`.
- Eksik XAF otomatik üretilir ve yalnızca **eksik şemalar** eşlenir; mevcut politika
  içeriği, elle yapılmış düzenlemeler dâhil, korunur.
- `create xaf` veya `create`, varsayılan XAF dosyasını oluşturup ona bağlanır.
- Komutlar `&` ile aynı satırda zincirlenebilir. `create xaf & connect to main.xaf`
  ve `create & connect to main.xaf` ifadeleri `main.xaf` dosyasını oluşturur ve
  bağlantıyı kurar. `create` burada hedefi takip eden `connect to` ifadesinden alır.

## 9. `state` — tek durum

```sph
state ad = "Arda"                    // string: tip çıkarımı
state yas: integer = 17              // açık tip bildirimi
state oran: float = 0.96
state aktif: boolean = true
state mesaj = "Merhaba, {ad}"        // string interpolation
state alan = 8 * (3 + 2)^2
state kok = sqrt(81)
set ad = "Elif"                    // mevcut state'i günceller
state secim = [gece aylik]
state bos = []
```

- Sözdizimi: `state <ad>[: <tip>] = <ifade>`.
- Tip belirtilmezse başlangıç değerinden çıkarılır. Desteklenen tipler:
  `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, `null`.
  `number`, `integer` veya `float` kabul eder.
- Açık tip ile değer uyuşmazsa `S242` oluşur. `integer` ve `float` birbirinden
  farklıdır; `number` ikisini de kabul eder.
- Aynı isimle farklı bir değer atanırsa mevcut state güncellenir; ilk değerle
  belirlenen tür korunur. Aynı isim ve aynı değer tekrar yazılırsa gereksiz tekrar
  olduğu için `S246` oluşur. Örnek: `state name = "arda"` ardından
  `state name = "elif"` güncellemedir.
- Değer, kendisinden önce tanımlanmış durumlara başvurabilir (`state b = a`).
- Metin birleştirme `+` ile yapılmaz. Metin içinde `{state_adı}` kullanılır;
  örneğin `state mesaj = "Merhaba, {ad}"`. Bilinmeyen state `S102` verir.
- Sayısal Expression Engine: `+`, `-`, `*`, `/`, `^`, parantez ve `sqrt(ifade)`.

### `set` — mevcut state'i açıkça güncelleme

`set`, önceden tanımlanmış bir state'in değerini günceller; yeni state oluşturmaz.
Değerin türü mevcut state'in türüyle uyumlu olmalı ve aynı değer tekrar atanamaz.

```sph
state name = "arda"
set name = "elif"
state age: integer = 18
set age = 19
```

Bilinmeyen state için `S284`, tür uyuşmazlığı için `S289`, aynı değerin tekrar
atanması için `S246` üretilir. `set` bir fonksiyonun `execute` bloğunda yalnızca
parametreleri veya daha önce tanımlanmış yerel state'leri güncelleyebilir; dış
kapsamdan gelen state'ler fonksiyon içinde salt okunurdur.

  `^` üs alma, `sqrt(...)` karekök işlemidir. Öncelik standart matematik
  kurallarına ve parantezlere göre belirlenir. Bölme sıfırsa `S243`, geçersiz
  veya sayısal olmayan ifade `S244` verir.
- Bu aşamada mantıksal operatörler ve karşılaştırmalar özellikle kapsam dışıdır.
- Ad `[A-Za-z_][\w]*` olmalı.
- Değer, kendisinden önce tanımlanmış durumlara başvurabilir (`state b = a`), çünkü
  ayrıştırıcı satırları sırayla işler.
- Nokta içeren ad **çalışmaz**: `state a2.x = 5` eşleşmez ve `S100` verir. Bu
  biçimdeki niyet `S109` ile daha açık bir şekilde bildirilir:
  `multi-state a2.x = 5` → `S109`.

## 10. `multi-state` — gruplanmış durum

Yeni bildirim biçimi `id` ve `state` bloğunu kullanır:

```sph
multi-state {
    id = "user"
    state {
        name = "Arda"
        age = 17
        trust = 0.96
    }
}
```

Aynı `id` ile alan güncellenebilir:

```sph
multi-state {
    id = "user"
    state {
        name = "Arda"
        age = 17
    }
}

multi-state {
    id = "user"
    state {
        age = 18
    }
}
```

Alan sırası `at [N]` ile değiştirilir; güncelleme ve sıralama birlikte yapılabilir:

```sph
multi-state {
    id = "user"
    state {
        name = "Arda"
        age = 17
        trust = 0.96
    }
}

multi-state {
    id = "user"
    state {
        age at [3]
        age = 18 at [2]
    }
}
```

Her grubun ilk bildiriminde en az iki alan tanımlanmalıdır. Sonraki güncelleme
blokları bir veya daha fazla mevcut alan içerebilir. Var olmayan alan eklenemez;
önce ilk bildirimde tanımlanmalıdır. Sıra 1 tabanlıdır ve mevcut alan sayısını
geçemez. Alan başvurusu `user.age` biçimindedir.

Eski `multi-state user { ... }` yazımı geçiş dönemi için kabul edilir; yeni
programlarda `id` / `state` biçimi kullanılmalıdır.

## 11. `surface` — çıktı

`surface` çekirdektir; `use` gerektirmez ve politikayla denetlenir (`X040`).
Yüzeysiz bir program sessizdir.

```sph
surface { ad }
surface { yas }
surface {
    ad
    yas
}
surface { ad }
surface { level }
```

| Girdi | Çıktı |
|---|---|
| `surface { ad }` | `ad = Arda` (tek durum başvurusu → etiketli) |
| `surface { ad }` | `ad = Arda` (tek state başvurusu → etiketli) |
| `surface { ad yas }` | iki ayrı satır |
| `surface { [gece aylik] }` | listeyi tek satırda basar |
| `surface { [gece aylik] }` | `[gece, aylik]` |
| `surface { sifre }` (gizli) | `sifre = *` |

Boş `surface` bloğu `S151` verir. Geçersiz öğe `S170`, başsız/trailing `+` `S171`,
kapanmamış tırnak `S172`. Bilinmeyen durum `S102`.

## 12. `ask` — soru

`ask` çekirdektir ve politikayla denetlenir (`X041`).

```sph
ask {
    id = "kimlik"
    prompt = "Kullanıcı adınız:"
    state = username
    type = "text"
    default = "anonim"
    suggestion = "örn. arda"
    secret = false
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | Tanılama etiketi. Durum adı **değildir**. |
| `prompt` | evet | Soru metni. |
| `state` | evet | Hedef durum adı, tırnaqsız. |
| `suggestion` | hayır | İstem yanında ipucu. Doğrulama değildir. |
| `type` | hayır | `"text"` (varsayılan) veya `"number"`. |
| `default` | hayır | Boş yanıtta veya süre dolduğunda kullanılan **sabit**. |
| `requirement` | hayır | `true` boş yanıtı reddeder; `false` atlamaya izin verir. |
| `duration` | hayır | Saniye cinsinden pozitif zaman sınırı. |
| `secret` | hayır | `true` ise maskeler ve gözlemden çıkarır. |

Kurallar:

- `id` olmadan `ask` `S161` verir; `prompt` olmadan `S162`; hedef olmadan `S199`.
- Aynı ayar iki kez `S164` verir.
- `type` yalnız `text`/`number` olabilir, aksi hâlde `S165`.
- `default` **sabit** olmalı; durum başvurusu `S166` verir.
- `secret` yalnız `true`/`false`, aksi hâlde `S163`.
- `ask` ya `state` ya `multi-state` kullanır, ikisini birden kullanamaz (`S163`).
- İstemler `stderr`'e yazılır, yanıt `stdin`'den okunur. Biten girdi bir hata
  `S164` verir; asla asılı kalmaz.
- `type = "number"` için hatalı yanıt yeniden sorulur.

### Çok alanlı tek `ask` — `multi-state` biçimi

```sph
ask {
    id = "tam"
    multi-state {
        ad    { prompt = "Adınız:" }
        sifre { prompt = "Parolanız:"  secret = true }
        yas   { prompt = "Yaşınız:"    type = "number"  default = 18 }
    }
}
```

Her alan bloğu kendi ayarlarını taşır ve `prompt` zorunludur (`S162`).

`ask` ayarları arasında `requirement` ve `duration` da bulunur:

```sph
ask {
    id = "nickname"
    prompt = "Takma ad:"
    state = nickname
    default = "guest"
    requirement = true
    duration = 15
}
```

- `duration` saniye cinsinden pozitif süredir. Süre dolunca soru sona erer.
- Süre dolduğunda `default` varsa o değer kaydedilir.
- `requirement = false` ise boş bırakılabilir; varsayılan yoksa `null` kaydedilir.
- `requirement = true` ve `duration` birlikteyse `default` zorunludur.
- `duration` olmadan `requirement = true` boş yanıtı tekrar ister.

Alan adları benzersiz olmalı (`S168`); en az bir alan gerekir (`S169`).

## 13. `multi-ask` — soru grupları

```sph
multi-ask {
    id = "iletisim"

    ask {
        id = "s1"
        prompt = "Şehir:"
        state = sehir
    }

    ask {
        id = "s2"
        prompt = "Ülke:"
        state = ulke
    }
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | Grup kimliği. Formda bölüm başlığı olarak kullanılır. |
| `ask` | en az bir | Her soru doğrudan `multi-ask` içinde kardeş blok olarak yazılır. |

`multi-ask > ask` tek seviyeli yapıdır. Bir `ask` bloğunun içine başka `ask`
yerleştirilmez. Sorular kaynak sırasına göre tek tek sorulur. Boş grup `S172`
verir.

## 14. `confirmation` — seçimli soru

```sph
confirmation {
    id = "sozlesme"
    prompt = "Sözleşmeyi kabul ediyor musunuz?"
    choice {
        evet = true
        hayir = false
    }
    state = sozlesme
    requirement = true
    default = "hayir"
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | Tanılama etiketi. |
| `prompt` | evet | Soru metni. |
| `choice { }` | evet | En az bir seçenek. |
| `state = <ad>` | evet* | Seçilen **değer** buraya yazılır. |
| `multi-state { a b }` | evet* | Tam iki alan: `a` değeri, `b` kullanıcının yazdığı etiketi alır. |
| `requirement` | hayır | `true` ise yanıt zorunlu; `false` ise boş bırakılarak atlanabilir. |
| `default` | hayır | Boş/yanıtsız durumda seçilecek seçenek etiketi veya değeri. |
| `multiple-selection` | hayır | `true` ise liste seçilir ve `state` bir **liste** alır. |
| `min-selection` | hayır | En az kaç seçim. Varsayılan 1. |
| `max-selection` | hayır | En çok kaç seçim. Varsayılan seçenek sayısı. |

`*` — `state` ve `multi-state` biçimlerinden **birinin** zorunlu olması gerekir
(`S192`); ikisi birden kullanılamaz.

### `choice` seçenekleri

İki biçim vardır ve anlamları farklıdır:

```sph
choice {
    evet = true
    mavi = "Mavi"
    "kirmizi"
}
```

| Girdi | Kullanıcı ne yazar | Durum ne alır |
|---|---|---|
| `evet = true` | `evet` veya `1` | `true` |
| `mavi = "Mavi"` | `mavi` veya `2` | `"Mavi"` |
| `"kirmizi"` | `kirmizi` veya `3` | `"kirmizi"` |

`choice` bloğu **yorum satırı kabul etmez** (`S180`); açıklamaları bloğun dışına
yazın.

- Tırnaklı giriş, etiketi de değeri de kendisidir.
- `etiket = değer` biçiminde değer **sabit** olmalı; durum başvurusu `S181` verir.
- Etiketler benzersiz olmalı (`S183`); en az bir seçenek gerekir (`S182`).
- Kullanıcı yanıtı **seçenek numarasıyla** da verebilir.
- `requirement = false` ise boş yanıt confirmation'ı atlar; hedef state'e `null` yazılır.
- `default` tanımlıysa boş yanıt veya EOF durumunda varsayılan seçenek otomatik seçilir.

### Çoklu seçim

```sph
confirmation {
    id = "ozellik"
    prompt = "Hangi özellikler?"
    choice { gece = true  aylik = true  ekip = false }
    state = secilen
    multiple-selection = true
    min-selection = 2
    max-selection = 3
    requirement = true
}
```

```text
Hangi özellikler?  1) gece  2) aylik  3) ekip  (2-3 seçim)
1 3
```

```text
secilen = [true, false]
```

| Kural | Hata |
|---|---|
| `multiple-selection` için `requirement = true` şart | `S238` |
| Çoklu seçim `multi-state` ile yazamaz | `S239` |
| `min > max` | `S237` |
| `max` seçenek sayısından büyük | `S237` |
| `min-selection` / `max-selection` sayı değilse | `S237` |

Liste seçenek sırasına göre yazılır. Aralık dışı sayı veya listede olmayan bir
seçenek yeniden sorulur.

## 15. `multi-confirmation` — seçim grubu

```sph
multi-confirmation {
    id = "bildirim"
    confirmation {
        id = "sms"
        prompt = "SMS gönderilsin mi?"
        choice { evet = true  hayir = false }
        state = sms
        requirement = true
    }
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | Grup etiketi. |
| `confirmation` | en az bir | Her biri tam bir `confirmation` gövdesi. |

Blok yalnız `id` ve `confirmation` kabul eder (`S197`); hiç `confirmation`
yoksa `S198`.

## 16. `observer` ve `multi-observer` — birleşik gözlem sistemi

`observer`, hem mevcut dosyadan hem de başka bir `.sph` dosyasından kaynak
izleyebilir. Dış ve iç gözlem için ayrı `observe` deyimi yoktur.

`observer` için `use { observer }`, `multi-observer` için `use { multi-observer }`
gerekir. `multi-observer` kendi modülüdür; onu kullanmak için ayrıca `observer`
içe aktarılmaz. `multi-observer` içindeki `observer` blokları grup üyesi olarak
ayrıştırılır.

```sph
use { observer multi-observer }

state level = 12
multi-state {
    id = "user"
    state { name = "Arda" age = 18 }
}

observer {
    id = "local-user"
    description = "Yerel kullanıcı gözlemi"
    source = self

    watch {
        user
        user.age
        level
    }
}
```

`source = self` mevcut `.sph` dosyasını; `source = "main.sph"` harici bir
kaynağı belirtir. `watch` en az bir geçerli bileşen içermelidir:

- `state_name` — tek bir state.
- `multi_state_id` — multi-state grubunun tamamı.
- `multi_state_id.state_name` — grubun tek alanı.
- `self-observation` — belirtilen kaynak dosyanın bağlı olduğu XAF'ta
  `features.self-observation = true` ise kaynak dosyanın tamamı.

`self-observation` kullanıldığında kaynak dosyanın bağlı olduğu XAF'ta özellik
etkin olmalıdır. `watch` içinde tek başına yazılır; başka bir watch bileşeni
eklenmez, çünkü seçilen kaynağın tamamını izler. Aynı kaynak için ayrıca ikinci
bir observer tanımlanamaz. Mevcut dosyanın XAF'ında
`features.self-observation = true` ise ayrıca `source = self` kullanan observer
tanımlanamaz; mevcut dosyanın tamamı zaten özellik tarafından kapsanır.

Birden fazla gözlemci `multi-observer` içinde gruplanabilir:

```sph
state status = "ready"
multi-observer {
    id = "example"
    description = "Birleşik gözlemciler"

    observer {
        id = "user-watch"
        description = "Kullanıcı alanları"
        source = "main.sph"
        watch {
            user
            user.age
            level
        }
    }

    observer {
        id = "system-watch"
        source = self
        watch {
            status
        }
    }
}
```

Her observer için `id`, `source` ve en az bir `watch` bileşeni zorunludur;
`description` isteğe bağlıdır. Observer kimlikleri dosya genelinde benzersiz
olmalıdır. `observe` deyimi kaldırılmıştır; kullanılması `S100` üretir.

Gözlem ayarları XAF v2'de `config.observer { <numeric-id> { ... } }` profillerinde
kimlik üzerinden eşleştirilir. Profil bulunamazsa `X028` üretilir. Kaynak sınıfı
izinleri Observer profilinde değil, ilgili politikanın `access.source` bloğunda
tutulur. `self` ve `external` birbirinden bağımsız boolean değerlerdir ve
belirtilmeyen izin `false` kabul edilir. Ayrıntı için [`XAF_V2_SCHEMA.md`](XAF_V2_SCHEMA.md)
belgesindeki Observer bölümüne bakın.

## 18. XAF `features` — özellik anahtarları

Özellikler XAF'ta merkezi olarak tanımlanır. `self-observation`, observer'ın
`source` olarak gösterdiği `.sph` dosyasının bağlı olduğu XAF'ta etkin olmalıdır.
Bu özellik `watch` alanındaki `self-observation` bileşenini etkinleştirir:

```xaf
features {
    self-observation = true
}
```

Kaynak dosyanın XAF'ında özellik kapalıysa `watch { self-observation }` kullanımı
`O207` verir. Çalışan dosyanın kendi XAF'ında özellik açıksa `source = self`
kullanımı `X061` ile reddedilir.

## 20. `component` / `form` / `note` / `list` / `table`

`component`, kutuları gruplar. Her kutu türü **adıyla** içe aktarılır.

```sph
use { component }

component {
    id = "dashboard"
    note  { title = "Bilgi"  text = urun }
    list  { title = "Özellik" item = adet }
    table { title = "Özet"    row "alan" "deger"  row "adet" adet }
}
```

`component { }` içinde kutular çıplak da yazılabilir; `component` dışında ayrı
blok olarak da kullanılabilir:

```sph
use { form from component }

form {
    title = "Sipariş"
    ask { id = "a1" prompt = "Ad:" state = ad }
}
```

`component` bloğunun kendisi isteğe bağlı `id` alır. Bu kimlik, kutu kimliklerinden
ayrıdır. Her kutu ayrıca kendi `id`, `title` ve `width` ayarlarını taşır.

| Ortak ayar | Anlamı |
|---|---|
| `id` | Kutu etiketi. `title` yoksa başlık olarak kullanılır. |
| `title` | Üst çerçevede çizilen başlık. |
| `width` | Toplam satır genişliği. Varsayılan 60, en az 10 (`S205`). |

### `note` — salt okunur metin kutusu

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `text` | evet | En az bir satır. Boşsa `S208`. |

Her `text` bildirimi bir içerik satırıdır; metin veya operand alır. String birleştirme için `+` kullanmayın.

### `list` — numaralı öğeler

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `item` | evet | En az bir öğe. Boşsa `S210`. |

Her `item` bildirimi bir öğe satırıdır; metin veya operand alır. String birleştirme için `+` kullanmayın.

### `table` — sütun hizalı satırlar

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `row` | evet | En az bir satır. Boşsa `S211`. |

Her `row` **sütun operandlarından** oluşur. String birleştirme için `+` kullanmayın.

```sph
table {
    title = "Özet"
    row "alan" "deger"
    row "adet" adet
    row "toplam" adet
}
```

### `form` — etkileşimli kutu

```sph
component {
    form {
        id = "kayit"
        title = "Kullanıcı Kaydı"
        width = 60

        ask { id = "a1" prompt = "Adınız:" state = ad }
        surface { ad }

        multi-ask {
            id = "iletisim"
            ask {
                id = "sehir"
                prompt = "Şehir:"
                state = sehir
            }
            ask {
                id = "ulke"
                prompt = "Ülke:"
                state = ulke
            }
        }

        confirmation {
            id = "onay"
            prompt = "Onaylıyor musunuz?"
            choice { evet = true  hayir = false }
            state = onay
            requirement = true
        }
    }
}
```

```text
┌─ Kullanıcı Kaydı ─────────────────────────────┐
│ Adınız: Ali                                   │
│ ad = Ali                                      │
│ ── konum ──────────────────────────────────── │
│ Şehir: Istanbul                               │
│ Onaylıyor musunuz? evet                       │
└────────────────────────────────────────────────┘
```

> **Sıra önemlidir.** Form adımları kaynak sırasına göre, **tek tek ve anında**
> çalışır. Bir `surface` satırı, dolduran `ask`'ten önce geliyorsa durum henüz
> yoktur ve `S102` alırsınız. Yukarıda `surface { ad }`, `ad`'yi dolduran
> `ask`'ten sonra yazılmıştır. Alternatif: durumu formun dışında önce
> bildirin.

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `surface` | en az bir adım | Statik satır. |
| `ask` | | İstem satırı; yanıt satıra yazılır. |
| `confirmation` | | Seçim satırı. |
| `multi-ask` | | Grup `id`'si **bölüm başlığı** olur. |
| `multi-confirmation` | | Aynı. |

Form yalnızca bu adımları kabul eder; hiçbir adım yoksa `S206`, kapanmamış blok
`S201`.

**Bölüm başlığı:** `multi-ask` bloğunun kendi `id` değeri kullanılır. İçindeki
her `ask` kendi benzersiz soru `id` değerini taşır.

Form dışında istemler `stderr`'e gider, form içinde `stdout`'a; bu yüzden form
içeriği yakalanabilir. Gizli yanıt forma asla yansıtılmaz, yalnız `*` yazılır.

---

## 21. `file` — dosya işlemleri

`file` bir modüldür. Her işlem proje dizini içinde kalır ve `file-system` yetkisi
gerektirir.

```sph
use { file }

file {
    id = "depo"
    mkdir  { path = "cikti" }
    create { path = "cikti/rapor.txt" }
    write  { path = "cikti/rapor.txt" data = rapor_satiri }
    append { path = "cikti/rapor.txt" data = ek_satir }
    read   { path = "cikti/rapor.txt" state = rapor }
    list   { path = "cikti" state = dosyalar }
    copy   { path = "cikti/rapor.txt" to = "cikti/yedek.txt" }
    move   { path = "cikti/yedek.txt"  to = "cikti/tasinmis.txt" }
    delete { path = "cikti/tasinmis.txt" }
    zip    { path = "cikti"        to = "arsiv.zip" }
    unzip  { path = "arsiv.zip"    to = "acilis" }
}
```

`file` bloğunda yalnızca `id` ve işlem adları kabul edilir.

| İşlem | Anlamı | `path` | `to`/`state` |
|---|---|---|---|
| `create` | Yeni dosya oluştur | zorunlu | — |
| `write` | Dosyayı üzerine yaz | zorunlu | — |
| `append` | Dosyanın sonuna ekle | zorunlu | — |
| `read` | İçeriği duruma oku | zorunlu | `state` |
| `list` | Klasör içeriğini duruma oku | zorunlu | `state` |
| `delete` | Dosya veya klasör sil | zorunlu | — |
| `copy` | Kopyala | zorunlu | `to` **zorunlu** |
| `move` | Taşı | zorunlu | `to` **zorunlu** |
| `mkdir` | Klasör oluştur | zorunlu | — |
| `zip` | Sıkıştır | zorunlu | `to` **zorunlu** |
| `unzip` | Aç | zorunlu | `to` **zorunlu** |

| Ayar | Anlamı |
|---|---|
| `path` / `from` | Kaynak yol, **tırnaklı**. |
| `to` | Hedef yol, tırnaklı. |
| `state` | Sonucun yazılacağı durum adı, tırnaksız. |
| `data` | Yazılacak içerik; string interpolation önceden bir `state` içinde hazırlanabilir. Legacy `+` birleştirmeyi yeni kodda kullanmayın. |

| Kural | Hata |
|---|---|
| Tırnaksız yol | `S225` / `S223` |
| `to` ve `state` birlikte | `S223` |
| `copy`/`move`/`zip`/`unzip` için `to` eksik | `S225` |
| `path` eksik (`list` dışında) | `S225` |
| Tanınmayan ayar | `S224` |
| Hiç işlem yok | `S226` |
| Kapanmamış blok | `S220` |

### Dosya sistemi yetkisi

Politika iki bağımsız eksen taşır: dosya ve klasör.

```xaf
config {
    file-system {
        allowed_path {
            "cikti"
            "arsiv.zip"
        }
        forbidden_path {
            "secrets"
            "private"
        }
        action {
            file   { create read modify copy move }
            folder { create read zip-unzip }
        }
    }
}

policy {
    id = 2001
    access { file-system }
    action {
        read = true
        write = true
        modify = true
        remove = true
        create = true
    }
}
```

| İşlem | Gereken yetki |
|---|---|
| `create` | `file { create }` |
| `write`, `append` | `file { modify }` |
| `read` | `file { read }` |
| `list` | `folder { read }` |
| `delete` | `file { delete }` veya `folder { delete }` |
| `copy` | `file { copy }` — kaynak **ve** hedef için |
| `move` | `file { move }` — kaynak **ve** hedef için |
| `mkdir` | `folder { create }` |
| `zip`, `unzip` | `folder { zip-unzip }` |

| Ayar | Anlamı |
|---|---|
| `allowed_path` | Zorunlu. İzin verilen proje içi yollar. |
| `forbidden_path` | İsteğe bağlı. Her durumda yasaklanan yollar. |
| `allowed_path = "data"` | Tek yol |
| `allowed_path { "data" "output" }` | Yol listesi |
| `forbidden_path { "secrets" "private" }` | Yasak yol listesi |

`config.file-system` ayarları `policy.access.file-system` izniyle birlikte uygulanır.
Global politika eylemi de ayrıca gerekir; örneğin SPH `write` / `append` işlemi
`policy.action.write = true` ve `config.file-system.action.file { modify }` ister.

`allowed_path` ve `forbidden_path` boş olmayan, göreli ve proje dışına çıkmayan
yollar olmalıdır. `allowed_path` verilmemişse XAF reddedilir. Yasaklı yol,
izin listesinde bulunsa bile reddedilir. `file-system` çıplak yetki olarak
kullanılamaz; kapsamlı blok zorunludur.

**Sıralama önemlidir.** Her yol önce çözülür ve proje içinde olduğu doğrulanır
(`F010` mutlak yol, `F012` dışarıda), **sonra** politika sorgulanır. Böylece izin
verilen bir klasörü adıyla yazmak yol kaçışı sağlayamaz. `unzip`, hedef klasörün
dışına çıkan girdi içeren arşivi reddeder (`F017`).

## 22. `execute` — program ve komut çalıştırma

```sph
use { execute }

execute {
    file = "alt.sph"
}
execute {
    command = "sophon-lsp"
}
```

| Ayar | Anlamı |
|---|---|
| `file` | Çalıştırılacak başka bir `.sph`. |
| `command` | Kayıtlı Sophon komutu. |

| Kural | Hata |
|---|---|
| İkisinin biri yok | `S232` |
| İkisi birden | `S233` |
| Aynı ayar iki kez | `S233` |
| Tırnaksız değer | `S231` |
| Kapanmamış blok | `S230` |

`command` **kabuğa asla gitmez.** Sophon komutları iç bir kayıt defterinden
çözülür ve bu kayıt defteri şu anda **boştur**. Politika bir komutu tanımıyorsa
`X054` verilir; yetki tanımlıysa "bulunamadı" hatası verilir. Bu kasıtlıdır:
komut adı bir metindir ve kabuğa verilen bir metin politikayı atlatmanın
yoluydu.

`file`, başka bir programı **kendi politikasıyla** çalıştırır. Zincir döngüyü önlemek
için derinlik sınırı 4'tür (`S234`). Yetki verilmemişse `X053`.

```xaf
config {
    execute {
        file {
            "alt.sph"
        }
        command { }
    }
}

policy {
    id = 2001
    access { execute }
    action { read = true }
}
```

## 23. `database` — Sophon Vault

`database` bir **takma addır**: `database <ad> { ... }`.

```sph
use { database }

database users {
    connect = users.svt

    read   { id = 1 }
    write  { id = 2  name = "Zeynep"  age = 19 }
    modify { id = 2  age = 20 }
    remove { id = 2 }
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `connect` | evet | `.svt` dosyası. `connect = x.svt` veya `connect to x.svt`. |
| `read` | | Kayıt okuma |
| `write` | | Yeni kayıt ekleme |
| `modify` | | Kayıt güncelleme |
| `remove` | | Kayıt silme |

İşlem gövdesi serbest `alan = değer` çiftleridir; `state` değerleri genişletilir.

| Kural | Hata |
|---|---|
| Geçersiz `connect` (`.svt` değil) | `S140` |
| Kapanmamış blok | `S143` |
| `write` için `id` yok | `V008` |
| `write` var olan bir `id` | `V009` |
| `modify` belirsiz eşleşme | `V010` |
| Vault dosyası yok | `V005` |
| Politika verilmemiş | `X026` |

`id` birincil anahtardır. `id` olmadan yazılan kayıt hiçbir zaman
değiştirilemez veya silinemez, bu yüzden çalışma zamanı böyle kayıt oluşturmayı
reddeder.

Veritabanı bağlantı yolları programın proje kökü içinde çözülür. Mutlak yol,
`..` ile kök dışına çıkış veya proje dışına açılan sembolik bağlantı `F010`/`F012`
ile reddedilir. Vault güncellemeleri geçici dosyaya yazılır ve atomik olarak
asıl dosyanın yerine geçirilir; kaydetme hatasında eski dosya korunur (`V015`).

## 24. `agent` — ajanlar

`use { agent }` gerekir. Üç ajan deyimi vardır.

### `agent connect` — bağlantı

```sph
use { agent }

agent connect {
    id = 1001
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | XAF v2 Agent kaydına bağlanan pozitif tam sayı. |

`id` yoksa `A001`, geçersizse `A002`, blok kapanmamışsa `A003`. Yalnız `id`
kabul edilir; başka bir deyim `A002` verir. Çıplak `agent { }` tamamen
kaldırılmıştır: `A015`.

### `agent run` — mesaj veya görev

```sph
state answer = ""

agent run {
    id = 1001
    message {
        "Selam, sophon-a."
    }
    output = answer
}
```

Görev biçimi de aynı `agent run` bloğunda kullanılabilir; `message` ve `task`
birlikte yazılamaz:

```sph
state analysis = ""

agent run {
    id = "a8alpl"
    task {
        "Kaynak kodunu analiz et."
    }
    output = analysis
}
```

### `agent task` — görev

```sph
agent task {
    id = "a8alpl"
    task {
        "Görev bir"
    }
}
```

| Ayar | Zorunlu | Anlamı |
|---|---|---|
| `id` | evet | Ajan kimliği, tırnaklı. |
| `message` / `task` | evet | `agent run` içinde bunlardan tam biri; `agent task` içinde yalnız `task`. |
| `output` | hayır | `agent run` yanıtını yazılacak state adı. |
| `input` | hayır | Ek dosyalar. |

```sph
agent run {
    id = 1001
    message {
        "Bu görseli incele."
    }
    input {
        file = "diagram.png"
        file = "notlar.txt"
    }
}
```

`input` yalnız `file` kabul eder. Blok var ama `file` yoksa `A041`; geçersiz
değer `A041`. Dosya yolları SPH dosyasına göre çözülür.

| Kural | Hata |
|---|---|
| `id` yok | `A004` |
| `message`/`task` içeriği yok | `A005` |
| Aynı ayar iki kez | `A008` |
| Kapanmamış blok | `A009` |
| Ajan XAF'ta yok | `A010` |
| Ajan bu SPH'ye bağlı değil | `A011` |
| `execute = true` değil | `A012` |
| Politika `read` izni vermiyor | `A013` |
| `AGENT.md` yok | `A026` |
| `-f` ile verilen program yok | `A027` |

`run` ve `task` blokları **kaynak sırasına** göre çalışır. `input` yetkisi
reddedilirse `A042`; dosya proje dışındaysa `A042`; boyut sınırı aşılırsa `A042`.

Görüntü türleri (`.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`) base64 veri URI'si
olarak gönderilir; diğer her şey UTF-8 metin olmalıdır. API anahtarı XAF'ta
**saklanmaz**; `api-key.key` ile adı verilen ortam değişkeninden okunur.

---

## 24A. Multi-agent tasarım taslağı (henüz uygulama söz dizimi değildir)

Multi-agent mimarisi, mevcut tekil `agent run` davranışını bozmadan ayrı bir
`multi-agent` yapısı olarak tasarlanacaktır. Önerilen SPH sorumlulukları:

- `multi-agent { id }`: orkestrasyon grubunu tanımlar.
- `agent { id, role }`: gruptaki bir uzman ajanı tanımlar; her ajan kendi
  `message { ... }` ve/veya `task { ... }` girdilerine sahip olabilir.
- Grup seviyesindeki `message` / `task`: tüm ajanlara ortak girdi sağlar.
- Tek içerik için `message = "..."` / `task = "..."` kısa biçimi;
  çoklu içerik için sıralı `message { "..." ... }` / `task { ... }` listesi.
- Her mesaj/görev ayrı bir iş öğesi olarak sırayla yürütülür; sonuçlar iş öğesi
  kimliği ve ajan kimliğiyle ilişkilendirilmiş kayıtlar halinde tutulur.
- `output` için tasarım kararı henüz verilmedi: tek state'e son yanıtı yazmak,
  sonuç listesini tek state'e yazmak veya her iş öğesine ayrı output state'i
  tanımlamak seçenekleri değerlendirilecek.

Çoklu Agent grupları, Agent'lar arası mesajlaşma, görev devri, ortak bağlam ve
paralel yürütme sonraki Agent runtime aşamalarının konularıdır. Bunların tasarım
notları `MULTI_AGENT_DESIGN.md` içinde tutulur; henüz çalıştırılabilir özellik
olarak kabul edilmemelidir.


## 24B. `function` — fonksiyon tanımı ve çağrısı

Fonksiyonlar `input → execute → output` yapısını kullanır. Fonksiyon, çağrılmadan
önce tanımlanmalıdır. Parametre tipleri ve çalışma zamanı kuralları
[`FUNCTIONS_DESIGN.md`](FUNCTIONS_DESIGN.md) içinde açıklanır.

```sph
function {
    id = "calculate"
    input {
        a: integer
        b: integer = 10
        c: integer?
    }
    execute {
        state temporary = a * b
        state result = temporary + 10
    }
    output: integer = result
}

state total = calculate(2)
state named = calculate(a = 3, b = 4)
```

Çoklu sonuçlar object olarak döner:

```sph
function {
    id = "stats"
    input { a: integer b: integer }
    execute { state sum = a + b state difference = a - b }
    output { sum difference }
}
state results = stats(9, 4)
state total = results.sum
```

Fonksiyon state'leri yereldir ve dışarı sızmaz. Fonksiyon, çağrı anında mevcut dış state'leri okuyabilir ancak değiştiremez; aynı adlı yerel state dış state'i gölgeler.

## 24C. Control Flow tasarımı (henüz uygulanmadı)

Sophon Control Flow için `if/else` yerine `decide { when ... otherwise ... }` yapısı
seçilmiştir. Karşılaştırmalarda `!=`/`≠`, `>=`/`≥` ve `<=`/`≤` eş anlamlıdır.
`state` aynı isimle farklı değer aldığında güncellenir; `set` mevcut state güncellemesini
açıkça belirtir. Parser/runtime uygulaması henüz yapılmamıştır.

Tam sözdizimi, operatör önceliği, tip kuralları ve kapsam semantiği
[`CONTROL_FLOW_DESIGN.md`](CONTROL_FLOW_DESIGN.md) içindedir.

## 25. XAF dosyası

`.xaf` dosyası Sophon'un kontrol düzlemidir; doğrudan çalıştırılmaz, `.sph`
programından `connect to` ile bağlanır. Yeni projelerde XAF v2 kullanılmalıdır:

- `config {}`: multi, observer, database, file-system, execute ve Agent ortak ayarları.
- `agent {}`: sayısal ID'li Agent kaydı; sayısal Policy ID veya inline `policy {}` alır.
- `policy {}`: sayısal ID'li erişim ve eylem izinleri.
- `features {}`: `self-observation` gibi kök özellik anahtarları.

Güncel ve tam XAF referansı [`XAF_V2_SCHEMA.md`](XAF_V2_SCHEMA.md) dosyasındadır.
Aşağıdaki örnek, yeni şemanın temel bağlantısını gösterir:

```xaf
config {
    default-policy = 2001
    multi {
        multi-state
    }
    agent {
        permission { execute = true }
        security { container = false }
        timing {
            delay = 60
            timeout = 180
            retry { duration = 2 count = 3 }
        }
        input { max-token = 12000 max-bytes = 5242880 }
        output { max-token = 4096 }
        connection {
            provider = "openrouter"
            model = "provider/model-id"
            key = "OPENROUTER_API_KEY"
        }
    }
}

agent {
    id = 1001
    name = "Research Agent"
    policy = 2001
}

policy {
    id = 2001
    access {
        multi
        agent
    }
    action {
        read = true
        write = true
    }
}
```

### `config` başlıkları

| Başlık | İşlev |
|---|---|
| `multi` | Kullanılmasına izin verilen multi bileşenlerini listeler. `access.multi` izni de gereklidir. |
| `observer` | Numeric Observer ID ile eşleşen `watch`, `log`, `path`, `level` ve `action` profilini tutar. |
| `database` | Yerel `.svt` sağlayıcısı ve `max-records` / `max-bytes` sınırlarını tutar. |
| `file-system` | İzinli/yasaklı yollar ile dosya/klasör eylemlerini belirler. |
| `execute` | Çalıştırılabilecek `.sph` dosyalarının izin listesini tutar. `command` şu an boş kalır. |
| `agent` | Agent'ların ortak permission, security, timing, input, output ve connection varsayılanlarını tutar. |

### `policy.access`

V2'de yalnızca `multi`, `observer`, `database`, `file-system`, `execute`, `agent`
ve `component` yazılabilir. `source { self = true/false external = true/false }`
Observer kaynak türlerini sınırlar. `input`, `state`, `multi-state`, `surface` ve
`ask` bu listeye dahil değildir. Normal `surface`/`ask` ve olağan bileşenler
ek izin gerektirmez; multi bileşenler ise hem `access.multi` hem de `config.multi`
listesi gerektirir.

### `policy.action`

`read`, `write`, `modify`, `remove`, `create`, `reorder` anahtarları bağımsız
boolean izinlerdir. Erişim yeteneği ile eylem izni ayrı denetlenir. Örneğin Agent
çağrısı `access.agent`, `action.read` ve Agent kaydında `permission.execute = true`
gerektirir.

### `policy.deny`

Alt politika, üst politikadan miras aldığı yeteneği veya eylemi iptal edebilir:

```xaf
policy {
    id = 2001
    access { multi observer source { self = true external = true } }
    action { read = true }
}
policy {
    id = 2002
    inherits {
        id = 2001
        deny {
            access { multi source { external = true } }
            action { read = true }
        }
    }
}
```

Deny gerekmiyorsa `inherits = 2001` kısa biçimi kullanılır. Deny varsa üst
politikanın ID'si `inherits { id = ... }` içine yazılır ve `deny` aynı bloğun
altında bulunur. `deny.access` ve `deny.action` kalıtım boyunca önceliklidir.
Alt politika aynı izni yeniden verse bile açık deny kararı kaldırılamaz. Hatalı
deny bloğu `X117` üretir. Önceki v2 biçimindeki kök düzey `deny` geçiş için
okunur; yeni dosyalarda kullanılmamalıdır.

### Agent, Observer ve diğer ayrıntılar

Agent'ın `permission.execute`, `security.container`, `timing.delay/timeout/retry`,
`input.max-token/max-bytes`, `output.max-token` ve `connection.provider/model/key`
alanları; Observer log semantiği; file-system, execute ve database sınırları için
[XAF v2 şema belgesine](XAF_V2_SCHEMA.md) bakın.

### Geriye dönük uyumluluk

Parser eski `agent <ad> {}` / `policy <ad> {}` kayıtlarını ve eski Observer
profillerini okumayı sürdürür. Bunlar yeni projeler için önerilmez ve otomatik
olarak yeni şemaya dönüştürülmez. XAF'ta `connect` ve `rules` kök deyimleri hâlâ
geçersizdir; bağlantı SPH dosyasındadır, izin tanımı `policy` içindedir.

## 26. SVT dosyası

`.svt` dosyası bir `vault` bloğuyla başlamak zorundadır (`V004`).

```svt
vault {
    record {
        id = 1
        name = "Arda"
        age = 17
        tags = ["okul" "deneme"]
    }
    record {
        id = 2
        name = "Zeynep"
        age = 19
    }
}
```

- Alan adı `[A-Za-z_][\w]*` olmalı, değer `state` ile aynı sözlüğü kullanır.
- **Liste öğeleri tırnaklı olmalıdır.** `.sph` içinde `[okul deneme]` geçerlidir
  ama `.svt` içinde değildir; Vault'ta çıplak sözcük `V011` verir:
  `tags = ["okul" "deneme"]`.
- Kapatılmamış `record` `V002`; geçersiz alan `V001`; geçersiz değer `V011`;
  geçersiz sözdizimi `V003`.
- Dosya yalnızca `vault {`, `record {`, `}` ve alan satırlarından oluşabilir.
  Ayrıştırma satır tabanlıdır: `record {` kendi satırında olmalıdır.

---

## 27. CLI

```bash
sophon --help
sophon --version
sophon run program.sph
sophon agent -f program.sph -m "Selam."
sophon agent -f program.sph -t "Görev bir"
```

| Komut | Anlamı |
|---|---|
| `--help`, `-h`, `help` | Komut yardımını gösterir. |
| `--version` | Dil/çalışma zamanı sürümünü gösterir. |
| `run <dosya>` | Bir `.sph` çalıştırır. Tam olarak bir dosya ister. |
| `agent -f <dosya> -m <mesaj>` | Konuşma isteği. |
| `agent -f <dosya> -t <görev>` | Görev isteği. |

- İki ajan biçimi de programı `-f` ile adlandırır; **yerleşik varsayılan yoktur**.
- `-m` ve `-t` birlikte verilemez.
- `-f` mevcut bir dosyayı göstermelidir, aksi hâlde `A027`.
- Eksik/şüpheli argümanlar kullanım satırıyla çıkış kodu 2 verir.
- Her iki ajan biçimi de `-f`'nin gösterdiği programın `agent connect` ile
  bildirdiği **ilk** ajanı kullanır.

İki çıktı akışı vardır: `surface` ve form içeriği `stdout`'a, hatalar ve soru
istemleri `stderr`'e gider. Böylece `sophon run app.sph > sonuc.txt` yalnızca
programın yüzeyini yakalar.

Launcher çalıştırılabilir olmalıdır. Paylaşımlı depodan kopyalama izin
bitlerini düşürür:

```bash
chmod +x sophon sophon.py
```

### İlk program

```bash
mkdir -p proje && cd proje
cat > merhaba.sph <<'SPH'
connect to merhaba.xaf
state ad = "Dunya"
surface { greeting }
SPH
sophon run merhaba.sph
```

```text
Merhaba, Dunya
```

`connect` olmadan hiçbir program çalışmaz; `XAF` dosyası ilk çalıştırmada bu
program için kendiliğinden üretilir.

---

## Hata ve uyarı kataloğu

_Kaynak: `sophon.py`._

Aşağıdaki liste uygulamadaki hata kodlarını ve koşullarını gösterir.

### Axx — Ajan

- `A001` — Agent connect requires id.
- `A002` — Invalid agent id "…".
- `A003` — Unclosed agent connect block.
- `A004` — agent … requires id.
- `A005` — agent … requires … content.
- `A006` — Invalid agent content "…".
- `A008` — Invalid agent id "…".
- `A009` — Unclosed agent … block.
- `A010` — Agent "…" was not found in the connected XAF.
- `A011` — Agent "…" is not connected to this SPH.
- `A012` — Agent "…" execution is denied by XAF.
- `A013` — Agent "…" cannot … because its policy denies read.
- `A014` — No agent is configured for the CLI.
- `A015` — The standalone agent declaration is no longer supported.
- `A020` — Unsupported agent provider "…".
- `A021` — Agent API environment variable "…" is not set.
- `A022` — Agent model is not configured.
- `A023` — Agent provider request failed: HTTP ….
- `A024` — Agent provider request failed: …
- `A025` — Agent provider returned no message content.
- `A026` — AGENT.md was not found.
- `A027` — Agent program "…" was not found.
- `A031` — Agent delay must be a positive number of seconds.
- `A032` — agent run accepts exactly one of message or task.
- `A033` — Agent output state "…" is not declared.
- `A035` — Linux Agent sandbox could not be established; no unsandboxed fallback is allowed.
- `A036` — The Agent policy does not grant Agent access.
- `A037` — Agent text input exceeds `input.max-token`.
- `A038` — An Agent ID is declared more than once in the connection or program.
- `A041` — Invalid agent input "…".
- `A042` — Agent input is denied by policy for "…".
### Fxx — Dosya sistemi

- `F001` — Agent input path "…" could not be resolved.
- `F002` — Agent input "…" is outside the project directory.
- `F003` — Agent input file "…" was not found.
- `F004` — Agent input "…" is … bytes, over the … byte limit.
- `F005` — Agent input "…" is neither a known image nor UTF-8 text.
- `F010` — Path "…" must be relative to the project.
- `F011` — Path "…" could not be resolved.
- `F012` — Path "…" is outside the project directory.
- `F013` — "…" already exists.
- `F014` — "…" is not a file.
- `F015` — "…" is not a folder.
- `F016` — "…" already exists.
- `F017` — Archive entry "…" escapes the target folder.
- `F018` — "…" is a folder, not a Sophon source file.
- `F019` — "…" was not found.
- `F020` — "…" is not valid UTF-8 text (…).
- `F021` — "…" could not be read (…).
- `F022` — "…" is not a zip file.
- `F023` — A file operation failed at the operating-system or text-decoding layer.
- `F024` — A ZIP archive is invalid or corrupt.
- `F025` — A ZIP source folder contains a symbolic link.
### Oxx — Gözlem

- `O201` — Observed source "…" was not found.
- `O207` — `watch self-observation` requires the XAF feature.
- `O208` — Unknown watched resource "…".


### Sxx — SPH dili: söz dizimi, durum, gözlem, bileşen, dosya, execute

- `S100` — Unknown statement: …
- `S102` — Unknown state "…"
- `S105` — A multi-state requires at least two fields on its initial declaration.
- `S106` — Invalid multi-state field.
- `S107` — Unknown multi-state field "…".
- `S108` — Multi-state position … must be 1 or greater.
- `S109` — Direct multi-state field updates are not supported.
- `S110` — Use block cannot be empty.
- `S111` — Unknown module "…".
- `S112` — Duplicate module import "…".
- `S114` — Module "…" is not imported.
- `S242` — State "…" expects a different value type.
- `S243` — Division by zero.
- `S244` — Invalid arithmetic expression.
- `S245` — `date` or `time` is reserved by the datetime module.
- `S246` — A state is assigned the same value again; remove the redundant assignment or use a different value.
- `S250` — A documented future feature or reserved module is not implemented in this runtime yet.
- `S251` — The `+` operator cannot concatenate surface or component text; use interpolation.
- `S252` — Invalid surface item; use a supported literal or a declared state.
- `S253` — Unclosed list in a surface block.
- `S254` — A component setting or content item uses the wrong block/assignment form.
- `S260` — Function requires a valid quoted identifier.
- `S261` — Function requires input, execute, and exactly one output declaration.
- `S262` — Invalid function parameter or optional/default parameter order.
- `S263` — Duplicate function id, parameter, or local state.
- `S264` — Unsupported statement inside function execute.
- `S265` — Function output block must contain unique local state names.
- `S266` — Function call depth exceeds the runtime limit.
- `S267` — Too many positional function arguments.
- `S268` — Unknown named function argument.
- `S269` — Function argument supplied more than once.
- `S270` — Required function argument is missing.
- `S271` — Function argument type mismatch.
- `S272` — Function local state type mismatch.
- `S273` — Function output refers to an undeclared local state.
- `S274` — Function output type mismatch.
- `S275` — Unknown function id.
- `S284` — `set` targets an unknown state or uses invalid syntax.
- `S289` — `set` value is incompatible with the existing state type.
- `S290` — `random` is reserved by the random module.
- `S291` — Random functions accept positional arguments only.
- `S292` — `random.integer` requires two integer bounds.
- `S293` — `random.integer` minimum exceeds maximum.
- `S294` — `random.float` / `random.boolean` does not accept arguments.
- `S295` — `random.choice` requires one list.
- `S296` — `random.choice` cannot select from an empty list.
- `S297` — Unknown random function.
- `S247` — A file operation is missing a required setting or uses a setting it does not support.
- `S248` — A file operation repeats a setting or supplies multiple source paths.
- `S120` — Invalid observer … "…".
- `S121` — Observer watch requires a valid component.
- `S122` — Unclosed watch block.
- `S129` — Observer id is required.
- `S130` — Duplicate observer "…".
- `S131` — Unclosed multi-observer block.
- `S132` — Invalid multi-observer description.
- `S133` — A multi-observer block accepts only observer blocks, found "…".
- `S134` — A multi-observer block requires at least one observer block.
- `S135` — A source already covered by self-observation cannot have another observer.
- `S140` — Invalid database connect "…".
- `S143` — Unclosed database block.
- `S147` — Database "…" has no connection.
- `S148` — Duplicate database connection or operation field.
- `S149` — Duplicate database alias in one SPH file.
- `S151` — A surface block cannot be empty.
- `S160` — Unclosed ask block.
- `S161` — An ask block requires an id.
- `S162` — An ask block requires a prompt.
- `S163` — Invalid … value "…".
- `S164` — Duplicate … in ask block.
- `S165` — Unknown ask type "…".
- `S166` — A default value must be a literal.
- `S167` — Invalid ask setting "…".
- `S168` — Duplicate ask field "…".
- `S169` — A multi-state ask requires at least one field.
- `S170` — Unclosed multi-ask block.
- `S171` — Trailing "+" in surface block.
- `S172` — A multi-ask block requires at least one ask block.
- `S173` — A multi-ask block accepts only direct sibling ask blocks.
- `S175` — Invalid duration or a required timed ask has no default.
- `S176` — A required timed ask timed out.
- `S180` — Invalid choice entry "…".
- `S181` — Choice "…" must map to a literal value.
- `S182` — A choice block requires at least one option.
- `S183` — Choice labels must be unique.
- `S184` — Unclosed confirmation block.
- `S186` — A confirmation block cannot declare … twice.
- `S189` — Invalid confirmation … "…".
- `S190` — A confirmation block requires a choice block.
- `S191` — A confirmation block requires a prompt.
- `S192` — A confirmation block requires a state target.
- `S193` — A confirmation multi-state must name exactly two fields.
- `S194` — Invalid confirmation field "…".
- `S195` — Unclosed multi-confirmation block.
- `S197` — A multi-confirmation block accepts only confirmation blocks, found "…".
- `S198` — A multi-confirmation block requires at least one confirmation block.
- `S199` — An ask block requires a state target.
- `S200` — Unclosed component block.
- `S201` — Unclosed form block.
- `S202` — "Duplicate … block in a component."
- `S203` — A component block requires at least one form.
- `S205` — Invalid … width "…".
- `S206` — A form requires at least one surface, ask, or confirmation.
- `S207` — Unclosed … block.
- `S208` — A note requires at least one text line.
- `S209` — Unclosed list block.
- `S210` — A list requires at least one item.
- `S211` — A table requires at least one row.
- `S220` — Unclosed file block.
- `S223` — Invalid state target "…".
- `S224` — Invalid file … setting "…".
- `S225` — File … requires a path.
- `S226` — A file block requires at least one operation.
- `S227` — File operation "…" is not implemented yet.
- `S230` — Unclosed execute block.
- `S231` — Invalid execute … "…".
- `S232` — An execute block requires a file or a command.
- `S233` — An execute block cannot declare … twice.
- `S234` — Execution depth limit of … reached.
- `S236` — Execute file "…" was not found.
- `S237` — Invalid … value "…".
- `S238` — A multiple-selection confirmation requires requirement = true.
- `S239` — A multiple-selection confirmation writes to a single state, not multi-state.
- `S240` — Unknown Sophon command "…".
- `S241` — Confirmation default does not match a choice, or is invalid for multiple selection.
### Vxx — Sophon Vault (`.svt`)

- `V001` — Invalid SVT record field.
- `V002` — Unclosed SVT record.
- `V003` — Invalid Sophon Vault syntax.
- `V004` — SVT file must contain a vault block.
- `V005` — Sophon Vault "…" was not found.
- `V006` — Database modify requires a matching id record.
- `V007` — Database remove requires a matching id record.
- `V008` — Database write requires an id.
- `V009` — "Database write duplicates existing id …."
- `V010` — "Database modify matched … records for id …."
- `V011` — Invalid Sophon Vault value: …
- `V012` — The Vault record count exceeds `config.database.max-records`.
- `V013` — A record declares the same field more than once.
- `V014` — Two Vault records have the same record ID.
- `V015` — Failed to save the Sophon Vault atomically; the prior file is preserved.
### Xxx — Kontrol düzlemi: XAF, politika, yetki, bağlantı

- `X001` — An SPH file can connect to only one XAF file.
- `X002` — Invalid SPH connect syntax.
- `X004` — XAF files cannot declare top-level connections.
- `X005` — The XAF policy keyword is "policy", not "rules".
- `X006` — Connected XAF "…" was not found.
- `X007` — self-observation must be declared inside features.
- `X008` — This SPH uses XAF-backed features but has no XAF connection.
- `X012` — Observe policy requires path.
- `X013` — path must be a string when log = true.
- `X014` — path must be null when log = false.
- `X015` — Observe policy requires an action block.
- `X016` — Duplicate action setting.
- `X017` — Action block cannot be empty.
- `X019` — Observe policy requires a log level when logging is enabled.
- `X020` — Duplicate action setting "…".
- `X021` — Agent "…" must define a policy.
- `X022` — Policy "…" for agent "…" was not found.
- `X023` — Policy inheritance cycle involving "…".
- `X025` — No policy is available to authorize "…".
- `X026` — Database access denied for "…".
- `X027` — Database action "…" denied for "…".
- `X028` — Observer "…" has no XAF observation policy.
- `X060` — Invalid or duplicate features.self-observation setting.
- `X061` — source = self conflicts with XAF self-observation.
- `X062` — XAF observe blocks have been removed; use observer policies keyed by id.
- `X063` — XAF self-observer blocks have been replaced by features.self-observation.
- `X064` — Observer policy requires a source permission block.
- `X070` — An Agent, Policy, or observer ID must be a positive integer.
- `X071` — Unknown policy access capability.
- `X072` — A policy access capability is declared more than once.
- `X073` — Invalid or duplicated `access.source` declaration.
- `X074` — Unknown or duplicated Agent setting/section.
- `X075` — Unknown or duplicated setting inside an Agent section.
- `X076` — Agent permission/security settings must be Boolean.
- `X077` — Agent token/byte limits must be positive integers.
- `X078` — Agent delay/timeout values must be positive seconds.
- `X079` — Agent connection values must be quoted strings.
- `X080` — Invalid, unknown, or duplicated retry setting.
- `X081` — Agent name is required and must be a string.
- `X082` — Agent block requires an ID.
- `X083` — Agent policy reference must be an integer.
- `X084` — Agent cannot combine an external policy reference with an inline policy.
- `X085` — Agent must reference or define a policy.
- `X086` — Unknown, duplicated, or missing Observer configuration setting.
- `X117` — Invalid explicit policy denial declaration.
- `X087` — Observer configuration requires a path setting.
- `X088` — Observer path must match the `log` enabled/disabled state.
- `X089` — Invalid or missing Observer log level.
- `X090` — Observer configuration requires a non-empty action block.
- `X091` — Invalid or duplicated Observer action.
- `X092` — Unknown multi-component configuration.
- `X093` — Duplicate multi-component configuration.
- `X094` — Invalid or duplicated numeric Observer configuration block.
- `X095` — Unknown, duplicate, or invalid database configuration setting.
- `X096` — Only the local SVT provider and one connection block are supported.
- `X097` — Invalid execute file/command configuration.
- `X098` — Duplicate or unknown config section.
- `X099` — XAF may contain only one root config block.
- `X100` — Duplicate or unknown root config setting.
- `X101` — Duplicate Agent ID.
- `X102` — Policy block requires an ID.
- `X103` — Unknown or duplicated Policy setting/block.
- `X104` — Duplicate Policy ID.
- `X105` — Invalid or unknown Policy action.
- `X106` — Unknown XAF root statement.
- `X107` — Unbalanced or unexpected XAF braces.
- `X110` — The governing Policy does not grant a required access capability.
- `X111` — A required multi component is not enabled in `config.multi`.
- `X112` — `config.file-system` requires at least one allowed path.
- `X113` — No executable file or command is configured for `execute`.
- `X114` — Invalid, duplicated, or unknown file-system path/action structure.
- `X115` — Duplicate file-system action in a file or folder permission list.
- `X116` — Observer log path must be non-empty and project-relative.
- `X065` — Invalid or duplicate observer source permission.
- `X066` — Observer source class is denied by XAF policy.

- `X031` — access … }} does not take a name list.
- `X033` — Parent policy "…" was not found.
- `X050` — File operation "…" is not granted by policy.
- `X051` — Unknown … action "…".
- `X052` — Path is outside the allowed paths.
- `X053` — Execution is not granted by policy.
- `X054` — Command "…" is not granted by policy.
- `X055` — Invalid project-relative policy path.
- `X056` — file-system requires a non-empty allowed_path.
- `X057` — Path is inside a forbidden_path.
