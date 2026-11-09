# Sophon SPH / XAF — Tam Söz Dizimi ve Politika Referansı

**Kaynak temeli:** Bu referans, paketteki `sophon.py` ayrıştırıcısı ve çalışma zamanı ile `SYNTAX.md`, `FUNCTIONS_DESIGN.md` ve `MULTI_AGENT_DESIGN.md` karşılaştırılarak hazırlanmıştır.

> **XAF sürüm notu:** Bu dosyada bulunan eski XAF örnekleri v1 uyumluluk katmanını
> belgeliyor. Yeni XAF tasarımında `config {}`, sayısal kimlikli `agent {}` ve
> `policy {}` kullanılır. Güncel, uygulanmış XAF şeması için önce
> [`XAF_V2_SCHEMA.md`](XAF_V2_SCHEMA.md) belgesini esas alın.

**Durum etiketleri**

- **Uygulandı:** Parser ve runtime tarafından destekleniyor.
- **Parser kabul ediyor / runtime sınırlı:** Sözdizimi okunuyor ancak davranışın tamamı uygulanmamış veya kısıtlı.
- **Tasarım kilitli, uygulanmadı:** Kullanıcı kararı var; henüz çalıştırılabilir SPH syntax'ı değil.
- **Planlandı:** Yol haritasında var; henüz kullanılabilir değil.

> Bu belge, önerilen gelecek syntax'ı mevcut runtime özelliği gibi göstermez. Çalışan sözdizimi için kaynak kod esas alınır.

---

## 1. Dosya ve program ilişkisi

| Dosya | Rol | Doğrudan çalıştırılır mı? |
|---|---|---|
| `.sph` | Program ve çalışma akışı | Evet |
| `.xaf` | Erişim, güvenlik ve yürütme politikaları | Hayır; bir SPH tarafından bağlanır |
| `.svt` | Sophon Vault veri dosyası | Hayır; SPH `database` işlemleriyle kullanır |

Bir SPH dosyası en fazla bir XAF dosyasına bağlanır:

```sph
connect to app.xaf
```

`connect` hedefi `.xaf` uzantılı göreli bir yol olabilir. Bir SPH'de ikinci `connect` kabul edilmez. `create` veya `create xaf`, varsayılan XAF'ı oluşturup bağlamak için üst düzey başlangıç yönergesidir; `create xaf & connect to custom.xaf` biçiminde zincirleme de desteklenir.

### Çalışma zamanı akışı

```text
1. SPH parse edilir ve use modülleri yüklenir
2. XAF yüklenir / eksik varsayılan şema eşlenir
3. Agent çağrıları
4. Database işlemleri
5. File işlemleri
6. Execute işlemleri
7. Ask ve confirmation istemleri
8. Surface ve component çizimleri
9. Observer snapshot/log işlemleri
```

`datetime` yerel modül olduğu için tek başına XAF erişim politikası gerektirmez. `surface`, `ask`, `file`, `database`, `execute`, `observer` ve Agent gibi dış yetenekler XAF'la ilişkilidir.

---

# 2. SPH — Program bileşenleri

## 2.1 SPH ağaç görünümü

```text
program.sph
├── create / create xaf                 [başlangıç yönergesi]
├── connect to <file>.xaf               [en fazla bir]
├── use { ... }                         [0 veya daha fazla modül içe aktarımı]
│   ├── datetime
│   ├── database
│   ├── observer
│   ├── multi-observer
│   ├── agent
│   ├── component / named box imports
│   ├── file
│   └── execute
│
├── state                               [0 veya daha fazla]
├── multi-state                         [0 veya daha fazla]
│
├── ask                                 [0 veya daha fazla]
├── multi-ask                           [0 veya daha fazla]
│   └── ask                             [1 veya daha fazla kardeş blok]
├── confirmation                        [0 veya daha fazla]
│   └── choice                          [zorunlu]
└── multi-confirmation                  [0 veya daha fazla]
    └── confirmation                    [1 veya daha fazla]
        └── choice
│
├── surface                             [0 veya daha fazla]
├── component                           [0 veya daha fazla]
│   ├── form                            [0 veya 1; component başına tür tekrarı yok]
│   │   ├── surface
│   │   ├── ask
│   │   ├── multi-ask
│   │   ├── confirmation
│   │   └── multi-confirmation
│   ├── note                            [0 veya 1]
│   ├── list                            [0 veya 1]
│   └── table                           [0 veya 1]
│
├── file                                [0 veya daha fazla işlem]
├── execute                             [0 veya daha fazla]
├── database <alias>                    [0 veya daha fazla işlem]
│   ├── read
│   ├── write
│   ├── modify
│   └── remove
│
├── agent connect                       [0 veya daha fazla]
├── agent run                           [0 veya daha fazla]
└── agent task                          [0 veya daha fazla]

Observer declarations (use ile etkinleştirilir):
├── observer
│   └── watch
└── multi-observer
    └── observer
        └── watch

Built-in namespace (use { datetime } sonrasında):
├── date
│   ├── day
│   ├── month
│   ├── year
│   ├── weekday
│   └── timezone
└── time
    ├── hour
    ├── minute
    └── second
```

## 2.2 İçe aktarma — `use`

**Durum: Uygulandı.** `use` bir veya daha fazla modülü, ya da `name from module` biçiminde belirli kutu adlarını içe aktarır.

```sph
use { datetime }
use { database observer multi-observer agent file execute }
use { component }
use { list from component }
use { form from component file }
```

| Alan | Zorunlu mu? | Açıklama |
|---|---:|---|
| Modül adı | Evet, en az 1 | Geçerli modül listesinde olmalı. |
| `name from module` | Alternatif | `component` içindeki belirli kutu türünü seçer. |

Şu an kabul edilen modüller:

| Modül | XAF gerekir mi? | Açtığı özellik |
|---|---:|---|
| `datetime` | Hayır | `date`, `time` ve alt alanları |
| `database` | Evet | `database <alias> { ... }` |
| `observer` | Evet | `observer { ... }` |
| `multi-observer` | Evet | `multi-observer { ... }`; ayrı modüldür |
| `agent` | Evet | `agent connect/run/task` |
| `component` | Evet | `component` ve kutu türleri |
| `file` | Evet | `file { ... }` |
| `execute` | Evet | `execute { ... }` |

`form`, `note`, `list`, `table` bağımsız modül adı değildir; örneğin `use { table from component }` kullanılır. `component` tüm kutu türlerini açar.

Kurallar: boş `use` yasaktır; aynı modül veya aynı named import iki kez eklenemez; tanınmayan modül reddedilir; modül içe aktarılmadan ilgili blok kullanılamaz.

## 2.3 XAF bağlantısı — `connect`

**Durum: Uygulandı.**

```sph
connect to app.xaf
```

| Parametre | Zorunlu mu? | Tip / kural | Varsayılan |
|---|---:|---|---|
| XAF yolu | Evet | Tırnaksız, `.xaf` ile biten yol | Yok |

- Bir SPH dosyasında yalnızca bir bağlantı olabilir.
- XAF yoksa runtime otomatik şema oluşturabilir.
- XAF bağlantısı bir yetki vermez; yalnızca politika dosyasını seçer.
- XAF'taki politika adı, Agent bağlı değilse SPH dosyasının adıyla eşleşir: `app.sph` için `policy app.sph { ... }`.

## 2.4 Tekil state — `state`

**Durum: Uygulandı.**

```sph
state name = "Arda"
state age: integer = 18
state ratio: float = 0.96
state active: boolean = true
state tags: list = [science math]
state next_year = date.year + 1
state squared = 4 ^ 2
state root = sqrt(81)
state greeting = "Hello, {name}"
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `name` | Evet | `[A-Za-z_][\\w]*` biçiminde state adı. |
| `: type` | Hayır | Açık tip bildirimi. Atlanırsa başlangıç değerinden çıkarılır. |
| `= expression` | Evet | Başlangıç değeri veya hesaplanan ifade; aynı isimle farklı değer verilirse güncelleme. |

Aynı isimle farklı bir değer atamak mevcut state'i günceller. Aynı isim ve aynı
değerin tekrarı gereksiz atama olarak `S246` verir. Güncelleme ilk atamada
belirlenen türü korur.

Desteklenen açık tipler: `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, `null`. `number`, integer veya float değeri kabul eder. Diğer açık tipler ilgili değer tipine tam uymalıdır. `object` tipi tanınır; fakat bu runtime sürümünde genel object literal yazımı bulunmaz.

### Expression Engine

| İşlem | Operatör / fonksiyon | Örnek |
|---|---|---|
| Toplama | `+` | `a + b` |
| Çıkarma | `-` | `a - b` |
| Çarpma | `*` | `a * b` |
| Bölme | `/` | `a / b` |
| Üs alma | `^` | `a ^ 2` |
| Karekök | `sqrt(expression)` | `sqrt(81)` |
| Gruplama | `( )` | `(a + b) * 2` |

`+` burada sayısal toplama operatörüdür. String birleştirme için kullanılmamalıdır. String interpolation, çift tırnak içindeki `{state_name}` biçimindedir:

```sph
state name = "Arda"
state message = "Hello, {name}"
```

Mantıksal operatörler ve karşılaştırmalar henüz eklenmemiştir.

**Önemli uygulama ayrımı:** String interpolation şu an `state` değer ifadesi değerlendirilirken çözülür. `surface` içinde doğrudan yazılan tırnaklı metnin içinde interpolation henüz dinamik olarak çözülmez; önce bir state'e atanmış metin gösterilebilir. Ayrıca mevcut renderer `surface` / bazı içerik alanlarında eski `+` birleştirme davranışını hâlâ kabul eder. Bu legacy davranıştır ve hedef dil kuralı değildir; yeni Sophon kodunda kullanılmamalıdır. Runtime'dan kaldırılması ayrı bir uyumluluk değişikliğidir.

## 2.5 Gruplanmış state — `multi-state`

**Durum: Uygulandı.**

```sph
multi-state {
    id = "user"
    state {
        name = "Arda"
        age = 18
        score = 0.95
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `id` | Evet | Grup kimliği; tırnaklı. |
| `state { ... }` | Evet | Alan bildirimleri. |
| İlk bildirimde alanlar | En az 2 | İlk oluşturma anında en az iki alan olmalı. |

Alanlar `name = value` biçimindedir. Alan güncellemesi için aynı `id` ile ikinci `multi-state` bloğu kullanılabilir; yalnızca önceden var olan alanlar güncellenebilir. Alan sırası `field at [N]` veya `field = value at [N]` ile 1 tabanlı olarak değiştirilebilir. Alan başvurusu `user.age` biçimindedir. Eski `multi-state user { ... }` yazımı geçiş dönemi uyumluluğu olarak kabul edilir.

## 2.6 Terminal çıktısı — `surface`

**Durum: Uygulandı.**

```sph
surface {
    name
    age
    date
    time
}
```

| İçerik | Zorunlu mu? | Açıklama |
|---|---:|---|
| En az bir çıktı öğesi | Evet | Bir state, grup alanı, literal veya liste. |
| Birden fazla öğe | Hayır | Her whitespace-ayrılmış öğe ayrı satırdır. |

- Tek başına state başvurusu `name = Arda` biçiminde etiketli basılır.
- Literal, liste veya birden çok operand düz metin olarak basılır.
- `surface` çekirdektir; `use` gerektirmez ancak XAF'ta `access { surface }` gerekir.
- Çıktı `stdout`'a gider; hata ve soru istemleri `stderr`'e gider.

## 2.7 Kullanıcı girdisi — `ask`

**Durum: Uygulandı.**

Tek alanlı kullanım:

```sph
ask {
    id = "nickname"
    prompt = "Takma adın:"
    state = nickname
    type = "text"
    default = "guest"
    suggestion = "örn. arda"
    requirement = false
    duration = 15
    secret = false
}
```

| Parametre | Zorunlu mu? | Tip / kabul edilen değer | Varsayılan |
|---|---:|---|---|
| `id` | Evet | Tırnaklı tanılama etiketi | Yok |
| `prompt` | Evet | Metin | Yok |
| `state` | Tek alan biçiminde evet | Tırnaksız hedef state adı | Yok |
| `multi-state { ... }` | Alternatif | Çok alanlı ask alanları | Yok |
| `suggestion` | Hayır | İpucu metni; doğrulama değildir | Yok |
| `type` | Hayır | `"text"` veya `"number"` | `text` |
| `default` | Hayır | Sabit literal; başka state başvurusu olamaz | Yok |
| `requirement` | Hayır | `true` / `false` | `false` |
| `duration` | Hayır | Pozitif saniye | Süresiz |
| `secret` | Hayır | `true` / `false` | `false` |

Kurallar:
- Tekli biçimde `state` zorunludur. Alternatif olarak `multi-state` içinde alan blokları tanımlanır; iki biçim birlikte kullanılamaz.
- `type = "number"` geçersiz metin yanıtını tekrar ister.
- `requirement = false` boş yanıtı kabul eder; default yoksa `null` kaydeder.
- `duration` bittiğinde varsa default kaydedilir.
- `requirement = true` ve `duration` birlikteyse default zorunludur ve `null` olamaz.
- `secret = true` yanıtı gizler ve observer snapshot'ından çıkarır.

Çok alanlı tek `ask`:

```sph
ask {
    id = "profile"
    multi-state {
        name {
            prompt = "Adın:"
        }
        age {
            prompt = "Yaşın:"
            type = "number"
            default = 18
        }
    }
}
```

Bu biçimde `multi-state` anahtarları hedef alan adlarıdır; her alanın `prompt` değeri zorunludur. Alan başına `suggestion`, `type`, `default`, `requirement`, `duration`, `secret` ayarları kullanılabilir.

## 2.8 Soru grubu — `multi-ask`

**Durum: Uygulandı.** İç içe ask değil, doğrudan kardeş ask bloklarıdır.

```sph
multi-ask {
    id = "birth-date"

    ask {
        id = "day"
        prompt = "Doğum günü:"
        state = birth_day
    }

    ask {
        id = "month"
        prompt = "Doğum ayı:"
        state = birth_month
    }

    ask {
        id = "year"
        prompt = "Doğum yılı:"
        state = birth_year
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| Grup `id` | Evet | Grup etiketi. |
| `ask { ... }` | En az 1 | Doğrudan `multi-ask` içinde kardeş blok. |
| Her `ask` içeriği | Evet | Tekli veya kendi çok alanlı ask şemasına uyar. |

Her ask kendi `id`/prompt/state kurallarını taşır. Grup içindeki sorular kaynak sırasına göre sorulur. Bir `ask` içine başka bir `ask` yerleştirilmez.

## 2.9 Seçimli girdi — `confirmation`

**Durum: Uygulandı.**

```sph
confirmation {
    id = "terms"
    prompt = "Koşulları kabul ediyor musun?"
    choice {
        yes = true
        no = false
    }
    state = accepted
    requirement = true
    default = "no"
}
```

| Parametre | Zorunlu mu? | Tip / kural | Varsayılan |
|---|---:|---|---|
| `id` | Evet | Tırnaklı tanılama kimliği | Yok |
| `prompt` | Evet | Metin | Yok |
| `choice { ... }` | Evet | En az bir benzersiz seçenek | Yok |
| `state = name` | `multi-state` yoksa evet | Sonuç state adı | Yok |
| `multi-state { value label }` | `state` yoksa evet | Tam iki alan; seçilen değer ve yazılan etiket | Yok |
| `requirement` | Hayır | Boolean | `false` |
| `default` | Hayır | Choice etiketi veya choice değeriyle eşleşmeli | Yok |
| `multiple-selection` | Hayır | Boolean | `false` |
| `min-selection` | Hayır | Pozitif/tamsayı seçim sınırı | `1` |
| `max-selection` | Hayır | Seçenek sayısını aşamaz | Seçenek sayısı |

Choice girdileri iki türdür:

```sph
confirmation {
    id = "color-choice"
    prompt = "Bir renk seç:"
    choice {
        yes = true
        blue = "Blue"
        "red"
    }
    state = selected_color
}
```

- `label = literal`: Kullanıcı etiketi seçer, state'e literal değer yazılır.
- Yalnız tırnaklı literal: Etiket ve değer aynıdır.
- Etiketler benzersiz olmalıdır.
- Kullanıcı seçenek numarasıyla da seçim yapabilir.
- `requirement = false` boş bırakmayı sağlar; default yoksa hedefe `null` yazılır. Default varsa eşleşen seçenek otomatik seçilir.
- `multiple-selection = true` iken `requirement = true` zorunludur ve tek bir default seçeneğe izin verilmez. Sonuç tek state içinde liste olur; `multi-state` hedefi kullanılamaz.

**Parser kabul ediyor fakat etkili davranış üretmeyen alanlar:** `suggestion`, `type`, `secret` confirmation içinde tanınır/doğrulanır ancak mevcut runtime bunları seçim davranışına uygulamaz. Yeni programlarda kullanmayın.

## 2.10 Seçim grubu — `multi-confirmation`

**Durum: Uygulandı.**

```sph
multi-confirmation {
    id = "preferences"

    confirmation {
        id = "email"
        prompt = "E-posta bildirimi?"
        choice { yes = true no = false }
        state = email_enabled
    }

    confirmation {
        id = "sms"
        prompt = "SMS bildirimi?"
        choice { yes = true no = false }
        state = sms_enabled
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| Grup `id` | Evet | Grup kimliği |
| `confirmation` | En az 1 | Doğrudan çocuk confirmation blokları |

Her çocuk tüm `confirmation` gerekliliklerine uyar.

## 2.11 Gözlem — `observer`

**Durum: Uygulandı.** `use { observer }` gerekir.

```sph
use { observer }

observer {
    id = "user-watch"
    description = "Kullanıcı durumları"
    source = self
    watch {
        user
        user.age
    }
}
```

| Parametre | Zorunlu mu? | Tip / kabul edilen değer | Varsayılan |
|---|---:|---|---|
| `id` | Evet | Benzersiz tırnaklı kimlik | Yok |
| `source` | Evet | `self` veya `"relative/path.sph"` | Yok |
| `watch { ... }` | Evet | En az bir geçerli hedef | Yok |
| `description` | Hayır | Tırnaklı açıklama | Boş |

`watch` girdileri:
- `state_name`: Tek state.
- `group_id`: Multi-state grubunun tamamı.
- `group_id.field`: Tek multi-state alanı.
- `self-observation`: Yalnız başına kullanılır; seçilen SPH kaynağının tamamını izler. Yanına başka watch satırı eklenemez.

Bir kaynak dosya için aynı anda ikinci observer tanımlanamaz; `self-observation` zaten tüm kaynağı kapsar. Harici kaynak `.sph` olmalı.

## 2.12 Gözlemci grubu — `multi-observer`

**Durum: Uygulandı.** `use { multi-observer }` gerekir; `use { observer }` yerine geçmez.

```sph
use { multi-observer }

multi-observer {
    id = "monitoring"
    description = "Birleşik gözlem"

    observer {
        id = "self-watch"
        source = self
        watch { status }
    }

    observer {
        id = "remote-watch"
        source = "worker.sph"
        watch { user }
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| Grup `id` | Evet | Tırnaklı grup kimliği |
| `observer { ... }` | En az 1 | Doğrudan çocuk gözlemci |
| `description` | Hayır | Tırnaklı grup açıklaması |

Her alt observer, tekil observer şemasına uyar. Observer kimlikleri SPH dosyası genelinde benzersiz olmalıdır.

## 2.13 Terminal bileşenleri — `component`, `form`, `note`, `list`, `table`

**Durum: Uygulandı.** `use { component }` veya örneğin `use { note from component }` gerekir.

### `component`

```sph
use { component }

component {
    id = "dashboard"
    note { title = "Info" text = "System ready" }
    list { title = "Tasks" item = "Research" item = "Analysis" }
    table { title = "Summary" row "Metric" "Value" row "Users" 120 }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `id` | Hayır | Tırnaklı kapsayıcı kimliği |
| Alt kutu | En az 1 | `form`, `note`, `list`, `table` |
| Aynı kutu türünü tekrarlama | Hayır | Bir `component` içinde her tür en fazla bir kez |

### Her kutu için ortak ayarlar

| Parametre | Zorunlu mu? | Tip / kural | Varsayılan |
|---|---:|---|---|
| `id` | Hayır | Tırnaklı kutu kimliği | Yok |
| `title` | Hayır | Tırnaklı başlık | `id` veya kutu adı |
| `width` | Hayır | Integer, en az `10` | `60` |

### `note`

```sph
note {
    id = "notice"
    title = "Notice"
    width = 60
    text = "This is a note"
    text = "Read only"
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `text` | En az 1 | Her `text` bildirimi bir içerik satırı |
| `id`, `title`, `width` | Hayır | Ortak kutu ayarları |

### `list`

```sph
list {
    title = "Items"
    item = "First"
    item = "Second"
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `item` | En az 1 | Her `item` bildirimi bir list öğesi |
| `id`, `title`, `width` | Hayır | Ortak kutu ayarları |

### `table`

```sph
table {
    title = "Metrics"
    row "Name" "Value"
    row "Requests" 120
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `row` | En az 1 | Her satır bir veya daha fazla sütun operandı alır |
| `id`, `title`, `width` | Hayır | Ortak kutu ayarları |

### `form`

```sph
form {
    id = "registration"
    title = "Registration"
    width = 60

    ask {
        id = "name"
        prompt = "Name:"
        state = name
    }
    surface { name }
    confirmation {
        id = "accept"
        prompt = "Accept?"
        choice { yes = true no = false }
        state = accepted
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `surface` | En az 1 adım şartını karşılayan seçeneklerden biri | Form içinde statik çıktı adımı |
| `ask` | Hayır | Soru adımı |
| `multi-ask` | Hayır | Soru grubu adımı |
| `confirmation` | Hayır | Seçim adımı |
| `multi-confirmation` | Hayır | Seçim grubu adımı |
| `id`, `title`, `width` | Hayır | Ortak kutu ayarları |

Formda en az bir adım bulunmalıdır. Adımlar kaynak sırasıyla çalışır; `surface` bir state'i oluşturan `ask` adımından önce gelirse state henüz mevcut olmayabilir. Form içinde yalnız bu beş adım türü kabul edilir.

## 2.14 Dosya işlemleri — `file`

**Durum: Uygulandı.** `use { file }` ve XAF `file-system` yetkisi gerekir.

```sph
use { file }

file {
    id = "workspace"
    mkdir  { path = "output" }
    create { path = "output/report.txt" }
    write  { path = "output/report.txt" data = report_text }
    append { path = "output/report.txt" data = suffix }
    read   { path = "output/report.txt" state = report_content }
    list   { path = "output" state = file_names }
    copy   { path = "output/report.txt" to = "output/report-copy.txt" }
    move   { path = "output/report-copy.txt" to = "output/archive.txt" }
    delete { path = "output/archive.txt" }
    zip    { path = "output" to = "archive.zip" }
    unzip  { path = "archive.zip" to = "unpacked" }
}
```

`file` bloğu parametreleri:

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `id` | Hayır | İsteğe bağlı etiket; runtime işlem yetkisini değiştirmez |
| İşlem bloğu | En az 1 | Aşağıdaki işlemlerden biri veya daha fazlası |

Her işlem için alanlar:

| İşlem | `path` | `to` | `state` | `data` |
|---|---:|---:|---:|---:|
| `create` | Zorunlu | — | — | — |
| `write` | Zorunlu | — | — | İsteğe bağlı; yoksa boş metin yazılır |
| `append` | Zorunlu | — | — | İsteğe bağlı; yoksa boş metin eklenir |
| `read` | Zorunlu | — | Sonucu almak için gerekli | — |
| `list` | Zorunlu | — | Sonucu almak için gerekli | — |
| `delete` | Zorunlu | — | — | — |
| `copy` | Zorunlu | Zorunlu | — | — |
| `move` | Zorunlu | Zorunlu | — | — |
| `mkdir` | Zorunlu | — | — | — |
| `zip` | Zorunlu | Zorunlu | — | — |
| `unzip` | Zorunlu | Zorunlu | — | — |

- `path` ve `from` kaynak yol için eşdeğer anahtar olarak parse edilir; yol tırnaklı olmalıdır.
- `to` hedef yolu, `state` hedef state adını belirtir; aynı işlemde ikisi birden kullanılamaz.
- `copy`, `move`, `zip`, `unzip` için `to` zorunludur.
- Tüm yollar SPH proje dizini içinde kalır; mutlak yol ve `..` ile dışarı çıkış reddedilir.
- XAF'taki `forbidden_path`, `allowed_path` içinde olsa bile önceliklidir.

**Doğrulama boşluğu:** Parser `read`/`list` için hedef `state` alanının bulunmamasını her durumda erken yakalamıyor. Bu işlemlerde `state` mutlaka verilmeli; aksi hâlde runtime hatası doğabilir.

## 2.15 Alt program / komut — `execute`

**Durum: Parser ve file-run desteği uygulandı; command registry boş.** `use { execute }` gerekir.

```sph
use { execute }

execute {
    file = "worker.sph"
}
```

veya:

```sph
execute {
    command = "registered-command"
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `file` | `command` yoksa evet | Çalıştırılacak `.sph` dosyası |
| `command` | `file` yoksa evet | Sophon command registry adı |
| İkisini birlikte | Yasak | Tam olarak biri kullanılmalı |

- Değer tırnaklı string olmalıdır.
- Dosya çağrısı alt programın kendi XAF politikasını kullanır.
- Özyinelemeli execute derinliği 4 ile sınırlıdır.
- Komut çağrısı shell'e gönderilmez. Mevcut `SOPHON_COMMANDS` registry'si boştur; dolayısıyla şu anda geçerli kayıtlı komut yoktur.
- XAF `access.execute` altında çalıştırılacak türü açıkça vermelidir.

## 2.16 Veri tabanı — `database <alias>`

**Durum: Temel Vault işlemleri uygulandı; read sonucu SPH state'ine bağlanmıyor.** `use { database }` ve XAF'ta alias yetkisi gerekir.

```sph
use { database }

database users {
    connect = users.svt
    read   { id = 1 }
    write  { id = 2 name = "Zeynep" age = 19 }
    modify { id = 2 age = 20 }
    remove { id = 2 }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| Alias (`users`) | Evet | SPH içindeki veritabanı kimliği; XAF `access.database` ile eşleşir |
| `connect` | Çalıştırma için evet | `.svt` dosya yolu; `connect = file.svt` veya `connect to file.svt` |
| `read` | Hayır, işlem | Kayıt alanlarına göre eşleşme arar |
| `write` | Hayır, işlem | Yeni kayıt ekler; benzersiz `id` gerekir |
| `modify` | Hayır, işlem | Mevcut `id` kaydını günceller |
| `remove` | Hayır, işlem | Mevcut `id` kaydını siler |

İşlem bloklarının içi serbest `field = value` çiftleridir. `id`, birincil anahtardır. `connect` parse aşamasında boş bırakılabilse de runtime bağlantı yoksa işlemi durdurur. En az bir işlem yazılması pratikte gerekir.

**Doğrulama boşluğu:** Mevcut runtime `read` eşleşmelerini hesaplıyor ancak bu kayıtları SPH state'ine yazan bir `state`/`output` parametresi sunmuyor. Database `read` sonucunu kullanmaya yönelik bir syntax henüz yok.

## 2.17 Tekil Agent — `agent connect`, `agent run`, `agent task`

**Durum: Tekil Agent uygulandı.** `use { agent }` gerekir. Multi-agent ile karıştırılmamalıdır.

### Bağlantı

```sph
use { agent }
agent connect {
    id = "researcher"
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `id` | Evet | XAF'ta tanımlı Agent kimliği |

### Mesaj veya görev çalıştırma

```sph
state answer = ""
agent run {
    id = "researcher"
    message {
        "Sophon dilinin mimarisini özetle."
    }
    output = answer
}
```

```sph
state analysis = ""
agent run {
    id = "researcher"
    task {
        "Kaynak kodunu analiz et."
    }
    output = analysis
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `id` | Evet | Agent kimliği |
| `message { ... }` | `task` yoksa evet | Yalnızca biri kullanılabilir |
| `task { ... }` | `message` yoksa evet | Yalnızca biri kullanılabilir |
| `output = state_name` | Hayır | Yanıtı mevcut SPH state'ine yazar; state önceden/sonradan bildirilebilir |
| `input { file = "..." }` | Hayır | Bir veya daha fazla dosya eki; yalnız `file` kabul edilir |

`message` ve `task` aynı `agent run` içinde birlikte kullanılamaz. İçerik satırları tırnaklı metin olmalıdır. Eski XAF v1 örneklerinde `access.input` kullanılır; XAF v2’de ek dosyalar `access.file-system`, `config.file-system` ve `action.read` ile yetkilendirilir. Bilinen PNG/JPG/JPEG/GIF/WEBP türleri görsel olarak gönderilir; diğer ekler UTF-8 metin olmalıdır. Ses/video girdisi mevcut tekil Agent runtime'ında desteklenmez.

### Yalnız görev

```sph
agent task {
    id = "researcher"
    task {
        "Birinci görevi tamamla."
        "İkinci görevi tamamla."
    }
}
```

`agent task` zorunlu olarak `id` ve `task` alır. `output` yalnız `agent run` tarafından desteklenir. Agent çağrısından önce programda aynı id için `agent connect` tanımı ve bağlı XAF'ta Agent tanımı olmalıdır.

## 2.18 Yerel tarih/saat — `datetime`

**Durum: Uygulandı.** `use { datetime }` gerekir; XAF yetkisi gerekmez.

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

| Yerleşik değer | Tip | Zorunlu parametre? | Açıklama |
|---|---|---|---|
| `date` | string | Yok | Yerel tarih `YYYY-MM-DD` |
| `date.day` | integer | Yok | Ayın günü `1..31` |
| `date.month` | integer | Yok | Ay `1..12` |
| `date.year` | integer | Yok | Yıl |
| `date.weekday` | integer | Yok | ISO 8601; Pazartesi `1`, Pazar `7` |
| `date.timezone` | string | Yok | Yerel IANA timezone; bulunamazsa sistem kısaltması/ofseti |
| `time` | string | Yok | Yerel saat `HH:MM:SS` |
| `time.hour` | integer | Yok | `0..23` |
| `time.minute` | integer | Yok | `0..59` |
| `time.second` | integer | Yok | `0..59` |

Bütün değerler `use { datetime }` sırasında alınan tek bir yerel zaman snapshot'ından üretilir; tek program parse'ı içinde tutarlıdır. `date` ve `time` adları modül yüklendikten sonra ayrılmıştır.

---

# 3. XAF — Politika ve güvenlik bileşenleri

## 3.1 XAF ağaç görünümü

```text
app.xaf
├── features
│   └── self-observation = true | false
│
├── agent <agent-id>
│   ├── name
│   ├── policy                           [zorunlu]
│   ├── connect { <program>.sph ... }
│   ├── execute
│   ├── container                       [reserved]
│   ├── delay
│   ├── input
│   │   └── max-bytes
│   └── api-key
│       ├── provider
│       ├── model
│       └── key                           [environment variable name]
│
├── policy <policy-name>
│   ├── inherits
│   ├── access
│   │   ├── state
│   │   ├── multi-state
│   │   ├── observer { <observer-id> ... }
│   │   ├── database { <alias> ... }
│   │   ├── surface
│   │   ├── ask
│   │   ├── input
│   │   ├── file-system
│   │   │   ├── allowed_path             [zorunlu]
│   │   │   ├── forbidden_path           [opsiyonel]
│   │   │   └── action
│   │   │       ├── file
│   │   │       └── folder
│   │   └── execute
│   │       ├── file
│   │       └── command { ... }
│   └── action
│       ├── read
│       ├── write
│       ├── modify
│       ├── remove
│       ├── create
│       └── reorder
│
└── observer
    └── <observer-id>
        ├── source
        │   ├── self
        │   └── external
        ├── watch
        ├── log
        ├── path
        ├── level
        └── action
            ├── read
            ├── modify
            ├── create
            ├── remove
            └── reorder
```

## 3.2 `features`

**Durum: Uygulandı.** Şu an tek özellik tanımlı:

```xaf
features {
    self-observation = true
}
```

| Parametre | Zorunlu mu? | Tip | Varsayılan |
|---|---:|---|---|
| `self-observation` | Hayır | Boolean | `false` |

Bu özellik observer içinde `watch { self-observation }` kullanımını yönetir. İzlenecek kaynak SPH dosyasının bağlı XAF'ında etkin olmalıdır. Bir dosyanın kendi XAF'ında self-observation etkinse o dosya için ayrıca `source = self` kullanan observer tanımlanamaz; bütün kaynak zaten kapsanır.

## 3.3 Agent yapılandırması — `agent <id>`

**Durum: Uygulandı; bazı alanlar parse edilir fakat runtime'da henüz etkisizdir.**

```xaf
agent researcher {
    name = "Research Agent"
    policy = "research-policy"

    connect {
        main.sph
    }

    execute = true
    container = false
    delay = 45

    input {
        max-bytes = 5242880
    }

    api-key {
        provider = "openrouter"
        model = "provider/model-id"
        key = "OPENROUTER_API_KEY"
    }
}

policy research-policy {
    action {
        read = true
    }
}
```

| Parametre | Zorunlu mu? | Tip / kabul edilen değer | Varsayılan / not |
|---|---:|---|---|
| Agent kimliği (`researcher`) | Evet | Başlıkta isim | SPH `agent connect id` ile eşleşir |
| `name` | Hayır | String | Yok; runtime prompt'ta kullanılır |
| `policy` | Evet | Aynı XAF içindeki policy adı | Eksikse Agent tanımı geçersiz |
| `connect { ... }` | Hayır | İzin verilecek `.sph` adları | Parse edilir; mevcut runtime'da bağlantı sınırı olarak kontrol edilmez |
| `execute` | Hayır | Boolean | `false` |
| `container` | Hayır | Boolean | `false`; ayrıştırılır ama **reserved / etkisiz** |
| `delay` | Hayır | Pozitif saniye; ondalık kabul edilir | `60` |
| `input { ... }` | Hayır | Girdi sınırları | Varsayılan 5 MiB |
| `input.max-bytes` | Hayır | Pozitif/non-negative integer | `5 * 1024 * 1024` byte |
| `api-key { ... }` | Hayır, söz dizimi açısından | Provider ayarları | Canlı Agent çağrısı için model ve ortam anahtarı gerekir |
| `api-key.provider` | Runtime için gerekli | Şu an yalnız `openrouter` | Varsayılan yok |
| `api-key.model` | Runtime için gerekli | Model kimliği | `model-id` placeholder çalışmaz |
| `api-key.key` | Hayır | Ortam değişkeni adı | `OPENROUTER_API_KEY` |

Gerçek API anahtarı XAF'a yazılmaz; `key` parametresi yalnızca environment variable adıdır. Runtime bu değişkeni process environment içinden okur. `container` ve XAF `connect` alanları şu an gerçek izolasyon/bağlantı kuralı uygulamaz; bu alanlar için runtime genişletmesi gerekir.

## 3.4 Politika — `policy <name>`

**Durum: Uygulandı.**

```xaf
policy base-policy {
    access {
        surface
    }
    action {
        read = true
        write = false
    }
}

policy research-policy {
    inherits = "base-policy"

    access {
        state
        multi-state
        surface
        ask
        input
        database {
            users
        }
    }

    action {
        read = true
        write = false
        modify = false
        remove = false
        create = false
        reorder = false
    }
}
```

| Parametre | Zorunlu mu? | Açıklama | Varsayılan |
|---|---:|---|---|
| Policy adı | Evet | SPH dosya adı veya Agent `policy` alanıyla eşleşir | Yok |
| `inherits` | Hayır | Aynı XAF içindeki üst policy | Yok |
| `access { ... }` | Hayır | Kaynak/yetenek izni | Hiçbir şeye izin verilmez |
| `action { ... }` | Hayır | Genel işlem izinleri | Hiçbir işlem izni verilmez |

Miras zinciri döngüsüz olmalı ve üst policy aynı dosyada bulunmalıdır. Çocuk policy'nin `action` anahtarları üsttekileri anahtar bazında ezer. `access` izinleri ise birleştirilir (union): çocuk policy, üst policy'den gelen bir access iznini `false` yazarak geri alamaz. Bu nedenle kalıtımı güven sınırlarını daraltma mekanizması olarak kullanmayın.

## 3.5 Policy `access` — yetenek ve kaynak kapsamı

**Durum: Uygulandı.** `access` içinde yalın satır, tüm kaynakları/yeteneği açar. `observer` ve `database` için isim listesi de kullanılabilir.

```xaf
policy access-example {
    access {
        state
        multi-state
        surface
        ask
        input

        observer {
            user-watch
        }

        database {
            users
            logs
        }

        file-system {
            allowed_path { "data" "output" }
            forbidden_path { "secrets" }
            action {
                file { create read modify move copy delete }
                folder { create read modify move copy delete zip-unzip }
            }
        }

        execute {
            file
            command { "sophon-lsp" }
        }
    }
}
```

| Access anahtarı | Zorunlu mu? | Biçim | Etkisi |
|---|---:|---|---|
| `state` | Hayır | Yalın anahtar | Parse edilip saklanır; mevcut runtime genel state okuma/yazma yetkisi olarak uygulamaz |
| `multi-state` | Hayır | Yalın anahtar | Parse edilip saklanır; mevcut runtime genel multi-state erişim yetkisi olarak uygulamaz |
| `observer` | Hayır | Yalın anahtar veya ad listesi | Parse edilip saklanır; mevcut runtime'da erişim kontrolü olarak kullanılmaz. Gerçek observer izni üst düzey `observer { <id> { ... } }` bloğundan doğrulanır |
| `database` | Hayır | Yalın anahtar veya alias listesi | Tüm veritabanları veya seçilen alias'lar |
| `surface` | Hayır | Yalın anahtar | Terminal çıktı yeteneği |
| `ask` | Hayır | Yalın anahtar | Kullanıcı girdisi yeteneği |
| `input` | Hayır | Yalın anahtar | Agent ek dosya girişi yeteneği |
| `file-system` | Hayır | İç içe blok | Yol ve dosya/klasör işlemi kapsamı |
| `execute` | Hayır | İç içe blok | SPH dosyası ve kayıtlı komut çalıştırma kapsamı |

`surface`, `ask`, `input`, `state`, `multi-state` için ad listesi biçimi yoktur. Örneğin `surface { terminal }` geçerli değildir; `surface` yalın satır olarak verilir. `file-system` yalın yazılamaz; mutlaka `allowed_path` taşıyan blok olmalıdır. Önemli: `state`, `multi-state` ve `access.observer` alanları mevcut sürümde parse edilip politika nesnesinde saklanır; ancak genel state erişimini veya observer iznini fiilen kısıtlamaz. Observer'ın gerçek kaynak, watch, log ve action izinleri üst düzey `observer` politikasından kontrol edilir.


**Gerçek runtime denetimi:** `surface`, `ask`, `input`, `database`, `file-system` ve `execute` için ilgili çalışma zamanı kontrolleri vardır. `state`, `multi-state` ve `access.observer` ise şimdilik parse edilen politika metaverisidir; tek başına erişimi engellemez. Observer denetimi üst düzey `observer` policy bloğunda yapılır.

## 3.6 File-system policy

**Durum: Uygulandı.**

```xaf
policy file-policy {
    access {
        file-system {
            allowed_path {
                "data"
                "output"
            }
            forbidden_path {
                "data/private"
                "secrets"
            }
            action {
                file {
                    create
                    read
                    modify
                    move
                    copy
                    delete
                }
                folder {
                    create
                    read
                    modify
                    move
                    copy
                    delete
                    zip-unzip
                }
            }
        }
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `allowed_path` | **Evet** | En az bir göreli, proje içi yol. Tek değer `allowed_path = "data"` veya liste bloğu olabilir. |
| `forbidden_path` | Hayır | Her koşulda yasaklı göreli yollar. `allowed_path` altında olsa da yasak geçerlidir. |
| `action` | Hayır | Dosya ve klasör izin blokları; tanımlanmazsa hiçbir file/folder eylemi verilmez. |
| `action.file` | Hayır | `create`, `read`, `modify`, `move`, `copy`, `delete` |
| `action.folder` | Hayır | `create`, `read`, `modify`, `move`, `copy`, `delete`, `zip-unzip` |

Yollar mutlak olamaz, `..` içeremez ve proje dışına çıkamaz. Yasaklı yol kontrolü izinli yol kontrolünden önce/bağımsız uygulanır; forbidden her zaman önceliklidir.

## 3.7 Execute policy

**Durum: Uygulandı; kayıtlı command desteği şu an boş.**

```xaf
policy execute-policy {
    access {
        execute {
            file
            command {
                "sophon-lsp"
                "registered-tool"
            }
        }
    }
}
```

| Parametre | Zorunlu mu? | Açıklama |
|---|---:|---|
| `file` | Hayır | SPH alt programı çalıştırma izni |
| `command { ... }` | Hayır | İzin verilecek command adları |

Her ikisi de ayrı ayrı açılabilir. `file` satırı yoksa SPH dosyası çalıştırılamaz. `command` adı listede değilse reddedilir. Runtime command registry'si şu an boş olduğu için command izin listesi tek başına çalışabilir bir komut sağlamaz.

## 3.8 Observer policy

**Durum: Uygulandı.** SPH observer `id` değeriyle eşleşen XAF child block gerekir.

```xaf
observer {
    user-watch {
        source {
            self = true
            external = false
        }
        watch = true
        log = true
        path = "logs"
        level = normal
        action {
            read = true
            modify = true
            create = true
            remove = true
            reorder = true
        }
    }
}
```

| Parametre | Zorunlu mu? | Tip / değer | Varsayılan |
|---|---:|---|---|
| Observer child id | Evet | SPH observer `id` ile aynı | Yok |
| `source { ... }` | Evet | `self`, `external` boolean izinleri | Her ikisi de `false` |
| `source.self` | Hayır* | Boolean | `false` |
| `source.external` | Hayır* | Boolean | `false` |
| `watch` | Evet | Boolean | Yok |
| `log` | Evet | Boolean | Yok |
| `path` | Evet | Tırnaklı klasör veya `null` | Yok |
| `level` | `log = true` iken evet | `compact`, `normal`, `detailed`, `debug` | Log kapalıysa `compact` |
| `action` | Evet | En az 1 action ayarı | Yok |

Observer action adları: `read`, `modify`, `create`, `remove`, `reorder`; her biri `true`/`false` alır. `log = true` ise `path` string olmalı; `log = false` ise `path = null` olmalı. `source` içinde belirtilmeyen izin `false` olur.

## 3.9 Policy `action` — genel işlem izinleri

**Durum: Uygulandı.**

```xaf
policy action-policy {
    action {
        read = true
        write = true
        modify = false
        remove = false
        create = false
        reorder = false
    }
}
```

| Parametre | Zorunlu mu? | Değer |
|---|---:|---|
| `read` | Hayır | `true`, `false`, `null` |
| `write` | Hayır | `true`, `false`, `null` |
| `modify` | Hayır | `true`, `false`, `null` |
| `remove` | Hayır | `true`, `false`, `null` |
| `create` | Hayır | `true`, `false`, `null` |
| `reorder` | Hayır | `true`, `false`, `null` |

Eksik, `false` veya `null` değer yetki vermez. Database işlemleri için bu action anahtarları doğrudan kontrol edilir. Agent çağrısı için ilgili Agent policy'de `read = true` gerekir.

## 3.10 XAF içinde şu an aktif olmayan / yer tutucu alanlar

- En üst düzey `database { ... }` bloğu XAF dosyası oluşturulurken yorumlu şablon olarak eklenebilir; mevcut `parse_xaf()` bunu veritabanı şeması olarak parse etmez.
- `agent.container` parse edilir fakat container izolasyonu çalıştırmaz.
- `agent.connect { file.sph }` parse edilir; mevcut runtime bu listeyi gerçek SPH bağlantı allowlist'i olarak doğrulamaz.
- `execute.command` policy allowlist'i parse edilir; fakat kayıt defteri boş olduğundan çalıştırılabilir komut bulunmaz.
- XAF'ta `connect`, `rules`, üst düzey `observe`, `self-observer` geçerli yapı değildir. Bağlantı SPH'de tanımlanır; policy anahtarı `policy` olur; self-observation `features` içinde tanımlanır.

---

# 4. SPH ↔ XAF bağlantı matrisi

| SPH bileşeni / işlem | Gereken `use` | XAF bağlantısı | Kontrol edilen parametre |
|---|---|---|---|
| `state`, `multi-state` | Yok | Genel okuma/yazma için XAF kapısı henüz yok | `access.state`, `access.multi-state` parse edilir ama runtime'da genel yetki denetimi yapmaz |
| `surface` | Yok | SPH policy | `access.surface` |
| `ask`, `multi-ask` | Yok | SPH policy | `access.ask` |
| `confirmation`, `multi-confirmation` | Yok | SPH policy | `access.ask` |
| `datetime` | `datetime` | XAF gerekmez | Yok |
| `observer` | `observer` | Üst düzey `observer { <id> { ... } }` child | `source`, `watch`, `log`, `path`, `level`, `action`, `features.self-observation`; `access.observer` fiilî kapı değildir |
| `multi-observer` | `multi-observer` | Her iç observer için aynı id eşleşmesi | Observer policy kuralları |
| `component` / kutular | `component` veya named box import | Kutu içindeki `surface`/`ask` yetenekleri | `access.surface`, `access.ask` |
| `file` | `file` | SPH/Agent policy | `access.file-system.allowed_path`, `forbidden_path`, file/folder action |
| `execute` | `execute` | SPH/Agent policy | `access.execute.file` veya command allowlist |
| `database <alias>` | `database` | `access.database` ve policy `action` | Alias + `read/write/modify/remove` |
| `agent connect/run/task` | `agent` | XAF `agent <id>` + onun `policy`'si | Agent `execute = true`, policy `action.read = true`; dosya eki için `access.input` |
| `multi-agent` | Tasarımda `multi-agent` | Henüz XAF şeması uygulanmadı | Kilitli tasarım belgesinde |
| `function` | — | Henüz uygulanmadı | Kilitli Function tasarım belgesinde |

### Yetki zinciri örneği

```text
program.sph
  │
  ├─ connect to app.xaf ───────────────────────────────┐
  │                                                    │
  ├─ surface { ... } ───── requires access.surface ────┤
  ├─ ask { ... } ───────── requires access.ask ────────┤
  ├─ file { ... } ──────── requires access.file-system│
  ├─ database users ────── requires database: users ───┤
  ├─ observer id=watch ─── requires observer: watch ───┤
  └─ agent connect id=bot ─ XAF agent bot ─ policy ────┘
```

## 4.1 SPH ve XAF birlikte — genel örnek

`main.sph`:

```sph
connect to main.xaf
use { datetime file observer }

state status = "ready"
state created_year = date.year

ask {
    id = "username"
    prompt = "Kullanıcı adın:"
    state = username
    requirement = true
}

file {
    create { path = "output/session.txt" }
    write { path = "output/session.txt" data = status }
}

observer {
    id = "status-watch"
    source = self
    watch { status }
}

surface {
    status
    created_year
    username
    date
    time
}
```

`main.xaf`:

```xaf
policy main.sph {
    access {
        surface
        ask
        file-system {
            allowed_path { "output" }
            forbidden_path { "output/private" }
            action {
                file { create read modify }
                folder { create read }
            }
        }
    }
    action {
        read = true
        write = true
    }
}

observer {
    status-watch {
        source {
            self = true
            external = false
        }
        watch = true
        log = true
        path = "logs"
        level = normal
        action {
            read = true
            modify = true
            create = true
            remove = true
            reorder = true
        }
    }
}
```

Bağlantıların özeti: `connect` XAF'ı seçer; `policy main.sph` programın policy'sidir; `access.surface` ve `access.ask` bu yetenekleri açar; file-system blok yolları ve işlemleri sınırlar; `observer.status-watch` SPH `id` ile aynı isimde olmalıdır. `state` ve `multi-state` satırları genel runtime izni değildir; bu örnekte bilerek eklenmemiştir.

## 4.2 Database ve SVT bağlantısı

```text
main.sph
  └─ database users { connect = users.svt ... }
       ├─ alias: users ──> XAF access.database { users }
       ├─ read/write/modify/remove ──> XAF policy action
       └─ connect path ──> users.svt
                              └─ vault { record { ... } }
```

Örnek `users.svt`:

```svt
vault {
    record {
        id = 1
        name = "Arda"
        active = true
    }
}
```

## 4.3 Agent bağlantısı

SPH:

```sph
connect to main.xaf
use { agent }

agent connect {
    id = "researcher"
}

state agent_answer = ""
agent run {
    id = "researcher"
    message {
        "Sophon syntax referansını özetle."
    }
    output = agent_answer
}
```

XAF:

```xaf
agent researcher {
    name = "Research Agent"
    policy = "agent-policy"
    execute = true
    delay = 45
    api-key {
        provider = "openrouter"
        model = "provider/model-id"
        key = "OPENROUTER_API_KEY"
    }
}

policy agent-policy {
    access {
        input
    }
    action {
        read = true
    }
}
```

`agent connect.id` XAF `agent` başlığıyla, XAF Agent içindeki `policy` ise aynı dosyadaki policy adıyla eşleşir. Canlı çağrı için geçerli provider/model ve ortam anahtarı gerekir.

---

# 5. Tasarımı kilitli ancak henüz uygulanmamış syntax

Bu bölüm mevcut runtime kodu değildir. Tasarım kararlarını kaybetmemek ve yanlışlıkla çalıştırılabilir gibi sunmamak için listelenmiştir.

## 5.1 Functions — tasarımı kilitli, parser/runtime uygulanmadı

```sph
function {
    id = "calculate"

    input {
        a: integer
        b: integer = 10
        c: integer?
        d: integer? = 1
    }

    execute {
        state temporary = a * b
        state result = temporary + 10
    }

    output: integer = result
}

state total = calculate(5)
```

Kararlar:
- `id`, `input`, `execute`, `output` yapısı.
- Fonksiyon içindeki tüm `state` değişkenleri yerel scope'tadır.
- `name: type` zorunlu parametredir.
- `name: type = value` default değerli parametredir; atlanabilir ve default kullanılır.
- `name: type?` optional parametredir; atlanırsa `null` olur.
- `name: type? = value` optional parametredir; atlanırsa default değer kullanılır.
- Tek dönüş `output: integer = result` biçimindedir.
- Çağrı `calculate(arg1, arg2)` biçimindedir; isimlendirilmiş argümanlar da tasarıma dahildir.
- Çoklu output biçiminin sonuç nesnesi ve tipi ayrıca kesinleştirilecektir.

## 5.2 Agent Team ve Multi-Agent — tasarımı kilitli, parser/runtime uygulanmadı

Bu yapılar kullanıcı tarafından tasarım düzeyinde onaylandı; mevcut parser bunları çalıştırmaz. Mevcut tekil `agent` modülünden farklıdır.

### `agent team` — yeniden kullanılabilir takım tanımı

```sph
use { agent }

agent team {
    id = "research-team"

    team {
        agent {
            id = "researcher"
            role = "Research"

            input {
                message = "Araştırma yap."
            }

            output {
                research_output
            }

            result = researcher_result
        }

        agent {
            id = "analyst"
            role = "Analysis"

            input {
                task = "Araştırma sonuçlarını analiz et."
            }

            output {
                analysis_output
            }

            result = analyst_result
        }
    }
}
```

`agent team` takımı tanımlar; kendiliğinden çalıştırmaz. Takım tanımı ile takımın çalıştırılması ayrı işlemlerdir.

### `multi-agent` — çalışma grubu

```sph
use { agent multi-agent }

multi-agent {
    id = "research-team-run"

    agent {
        id = "researcher"
        role = "Research"

        input {
            message {
                "Birinci özel mesaj"
                "İkinci özel mesaj"
            }
            task = "Araştırma sonuçlarını topla."
            file {
                "docs/source-a.pdf"
                "docs/source-b.pdf"
            }
            image = "images/diagram.png"
            audio = "audio/interview.wav"
            video = "video/lecture.mp4"
        }

        output {
            message {
                message_output_1
                message_output_2
            }
            task {
                task_output
            }
            file {
                file_output_1
                file_output_2
            }
            image {
                image_output
            }
            audio {
                audio_output
            }
            video {
                video_output
            }
        }

        result = researcher_result
    }

    agent {
        id = "analyst"
        role = "Analysis"

        input {
            task = "Araştırma sonuçlarını analiz et."
        }

        output {
            task_output
        }

        result = analyst_result
    }

    broadcast {
        message {
            "Bütün ajanlara ortak mesaj 1"
            "Bütün ajanlara ortak mesaj 2"
        }
        task = "Bütün ajanlara ortak görev."
    }

    output {
        researcher_result
        analyst_result
    }

    result = team_result
}
```

| Tasarım öğesi | Kural |
|---|---|
| Modül | `multi-agent`, `agent` modülünden ayrıdır; birlikte `use { agent multi-agent }` ile içe aktarılır. |
| `id` | Grup kimliği zorunludur. |
| `agent` | Bir veya daha fazla çocuk Agent tanımı. |
| `role` | Agent rolü; tasarımda kullanılır. |
| `input` | `message`, `task`, `file`, `image`, `audio`, `video` türleri. |
| Çoklu input | Her tür tek değer veya çoklu değer bloğu alabilir. |
| `output` | Her input öğesine karşılık benzersiz output state'i tanımlanır; sonuçlar birbirini ezmez. |
| `result` | Agent'ın yapılandırılmış çalışma sonucu için state hedefi. |
| `broadcast` | Yalnızca `message` ve `task` alır; gruptaki tüm Agent'lara dağıtılır. |
| Özel input | Agent içindeki `input` yalnızca o Agent'a gönderilir. |
| Çoklu output | Aynı türde N input varsa o türe ait N output state'i bulunur. |

Broadcast içindeki `file`, `image`, `audio` ve `video` yasaktır. Her bir input öğesi ve output state'i benzersiz olmalıdır.

### Multi-Agent XAF çalışma politikası

```xaf
agent {
    parallel = false
    timeout = 60

    retry {
        duration = 10
        count = 3
    }
}
```

| Parametre | Zorunlu mu? | Tip | Varsayılan | Anlamı |
|---|---:|---|---:|---|
| `parallel` | Hayır | Boolean | `false` | `false`: sırayla; `true`: paralel çalıştırma. |
| `timeout` | Hayır | Saniye | `60` | Grubun/çalışmanın toplam süre sınırı. |
| `retry` | Hayır | Blok | Tekrar yok | Deneme başarısız olursa yeniden deneme ayarları. |
| `retry.duration` | `retry` varsa evet | Pozitif saniye | `10` önerisi | Her deneme için zaman sınırı. |
| `retry.count` | `retry` varsa evet | Sıfır veya pozitif tam sayı | `3` önerisi | İlk deneme haricindeki tekrar sayısı. |

Toplam `timeout`, retry denemelerinin toplam süresine üst sınır koyar. Varsayılan çalışma sırası sıralıdır. Bu XAF şeması da henüz parse edilmez veya runtime'da uygulanmaz.

### Henüz kesinleştirilmemiş Agent genişletmeleri

`max-agents`, `max-parallel`, `max-work-items`, `stop-on-error` ve `depends-on` öneri listesidir; kullanıcı tarafından henüz kilitlenmiş uygulama parametreleri değildir.

## 5.3 Yerel standart kütüphane yol haritası

| Modül | Kısaltma / içerik | Durum |
|---|---|---|
| `datetime` | `date`, `time` | Uygulandı |
| `math` | Matematik built-in'leri | Planlandı |
| `system` | `sys` | Planlandı |
| `random` | Rastgele değerler | Planlandı |

Şu an yalnızca `datetime` modülü içe aktarılabilir.

---

# 6. Kaynakta doğrulanan önemli uygulama notları

1. **String birleştirme:** Sophon tasarım kuralı string birleştirme için `+` kullanmamak; `state message = "Hello, {name}"` biçiminde interpolation kullanmaktır. Buna rağmen mevcut surface/component/file veri tarayıcısında legacy `+` birleştirme yolu hâlâ kabul edilir. Bu parser/runtime farkı ayrı bir düzeltme gerektirir.
2. **Surface interpolation:** Interpolation state değeri hesaplanırken uygulanır; `surface` içindeki doğrudan tırnaklı literal metinde dinamik interpolation henüz yapılmaz. Önceden hazırlanmış state'i `surface { message }` ile yazdırın.
3. **Datetime snapshot:** Tarih/saat program parse edilirken bir kez alınan yerel snapshot'tır; uzun süre çalışan programda her okumada yeniden hesaplanmaz.
4. **Function:** `FUNCTIONS_DESIGN.md` tasarım belgesidir, çalışan syntax değildir.
5. **Multi-Agent:** `MULTI_AGENT_DESIGN.md` tasarım belgesidir, çalışan syntax değildir.
6. **Database read:** `read` sorgusu parse/çalıştırılır ancak sonuç şu an SPH state'ine aktarılamaz.
7. **File read/list:** `state` hedefi verilmelidir; parser bu eksikliği her durumda erken yakalamadığı için mutlaka belirtin.
8. **Agent:** Mevcut uygulama tekil Agent çağrısıdır. `message/task` destekler ve input dosya eki yalnız file'dır; video/audio ayrı girdi türü değildir.
9. **XAF Agent alanları:** `container` ve `connect` parse edilir ancak tam bir sandbox/connection enforcement henüz yoktur.
10. **Execute command:** Shell çalıştırılmaz; komut registry'si boş olduğundan kayıtlı komut bulunmamaktadır.
11. **XAF database root block:** Şu an yorumlu iskelet/yer tutucudur; aktif veri şeması değildir.

---

# 7. Kontrol listesi — SPH/XAF bağlantı denetimi

Bir projeyi gözden geçirirken:

- [ ] SPH dosyası bir XAF'a bağlanıyor mu?
- [ ] Kullanılan her modül `use` ile içe aktarılmış mı?
- [ ] `surface` kullanılıyorsa policy `access.surface` veriyor mu?
- [ ] `ask`/`confirmation` kullanılıyorsa policy `access.ask` veriyor mu?
- [ ] `file` işlemleri için `file-system.allowed_path` tanımlı mı?
- [ ] File işleminin eylemi doğru `file`/`folder` action altında izinli mi?
- [ ] Hassas yollar `forbidden_path` ile ayrıca engellenmiş mi?
- [ ] `database` alias'ı XAF'ta izinli mi ve işlem action'ı açık mı?
- [ ] Her SPH observer id'si için aynı id'li XAF observer policy var mı?
- [ ] Self-observation kullanılıyorsa kaynak XAF'ta `features.self-observation = true` mi?
- [ ] Agent için SPH `agent connect`, XAF `agent <id>`, aynı XAF'taki `policy`, `execute = true` ve `action.read = true` tanımlı mı?
- [ ] Agent file input kullanıyorsa policy `access.input` veriyor mu?
- [ ] Function veya multi-agent tasarımını yanlışlıkla çalışan syntax gibi kullanmıyor musun?
