# Sophon XAF v2 — Resmî Şema

Bu belge yeni XAF şemasının yetkili referansıdır. Yeni projelerde `config {}`, sayısal kimlikli `agent {}` ve `policy {}` blokları kullanılmalıdır. Eski `agent <ad> {}` ve `policy <ad> {}` biçimleri geriye dönük uyumluluk amacıyla okunmaya devam eder; yeni dosya üreticisi bunları üretmez.

`.xaf`, Sophon'un kontrol ve güvenlik katmanıdır. `.sph` programı çalıştırılır; XAF ise programın hangi kaynaklara erişebileceğini, hangi işlemleri yapabileceğini ve Agent/Observer/Database/File System/Execute bileşenlerinin nasıl yapılandırıldığını belirler.

## 1. Genel yapı

```xaf
config {
    default-policy = 2001

    multi {
        multi-ask
        multi-state
        multi-confirmation
        multi-observer
    }

    observer {
        1001 {
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

    database {
        connection {
            provider = "local"
        }
        max-records = 100000
        max-bytes = 52428800
    }

    file-system {
        allowed_path { "data" "output" }
        forbidden_path { "data/private" }
        action {
            file { create read modify move copy delete }
            folder { create read modify move copy delete zip-unzip }
        }
    }

    execute {
        file {
            "worker.sph"
            "processor.sph"
        }
        command { }
    }

    agent {
        permission {
            execute = true
        }
        security {
            container = false
        }
        timing {
            delay = 60
            timeout = 180
            retry {
                duration = 2
                count = 3
            }
        }
        input {
            max-token = 12000
            max-bytes = 5242880
        }
        output {
            max-token = 4096
        }
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
        observer
        database
        file-system
        execute
        agent
        component
        source {
            self = true
            external = false
        }
    }
    action {
        read = true
        write = true
        modify = true
        remove = false
        create = true
        reorder = false
    }
}
```

`config` tek bir kök bloktur. Ortak Agent varsayılanları `config.agent` içinde tutulur; kökteki her `agent {}` ayrı bir Agent kaydıdır. Tek bir XAF içinde birden fazla Agent tanımlanabilir. Her Agent kendi ayarlarını tekrar yazabilir; yalnızca açıkça belirtilen değerler ortak varsayılanların üzerine yazılır.

`default-policy`, Agent bağlantısı olmayan bir SPH programı için kullanılacak politika kimliğidir. Bir veya daha fazla Agent bağlandığında o Agent kayıtlarının `policy` alanı kullanılır.

## 2. Kimlikler

XAF v2'de Agent ve Policy kimlikleri pozitif tam sayı olmalıdır. Observer kimlikleri de SPH bildirimi ile `config.observer` profili arasında aynı sayısal değerle eşleşmelidir.

```xaf
agent {
    id = 1001
    name = "Research Agent"
    policy = 2001
}

policy {
    id = 2001
    access { agent }
    action { read = true }
}
```

Aynı ID türü içinde tekrar eden kimlikler reddedilir. Eski tırnaklı Agent/Observer kimlikleri yalnızca mevcut projeler için geçiş uyumluluğu sağlar; yeni XAF v2 dosyalarında kullanılmamalıdır. `multi-state` gibi veri grubu adları kaynak kimlikleridir; bunların string olarak kalması XAF nesne kimliklerini değiştirmez.

## 3. `config.multi`

`multi` bloğu uygulamanın hangi çoklu bileşenlerini kullanabileceğini listeler. Bir multi özelliğin çalışması için hem `policy.access` içinde `multi` izni hem de `config.multi` içinde ilgili özellik adı bulunmalıdır.

Şu an desteklenen değerler:

| Değer | Açıklama |
|---|---|
| `multi-ask` | Birden fazla ask girdisi |
| `multi-state` | Çok alanlı ve güncellenebilir durum grubu |
| `multi-confirmation` | Çoklu onay girdisi |
| `multi-observer` | Birden fazla Observer kaydı |

`multi-agent` henüz çalışma zamanında uygulanmadığı için geçerli bir `config.multi` değeri değildir.

## 4. `config.agent` ve Agent şeması

`config.agent`, Agent'lar için ortak varsayılanları tanımlar. Agent başına özel bir değer, aynı başlık altında doğrudan Agent bloğuna yazılarak varsayılanı geçersiz kılar.

| Başlık | Alan | Varsayılan / kural | Açıklama |
|---|---|---|---|
| Kimlik | `id` | Zorunlu, pozitif integer | Her Agent için benzersiz kimlik |
| Kimlik | `name` | Zorunlu string | Görünen Agent adı |
| Politika | `policy` | Zorunlu | Sayısal Policy ID veya inline `policy {}` |
| `permission` | `execute` | `false` | Agent isteğinin çalıştırılmasına izin |
| `security` | `container` | `false` | Container izolasyonu talebi |
| `timing` | `delay` | 60 saniye | Her bir sağlayıcı isteğinin zaman aşımı |
| `timing` | `timeout` | 180 saniye | Tüm Agent çağrısı için toplam süre sınırı |
| `timing.retry` | `duration` | 1 saniye | Yeniden denemeler arasındaki bekleme |
| `timing.retry` | `count` | 0 | İlk denemeye ek tekrar sayısı |
| `input` | `max-token` | Sınır yok | Metin girdi token tahmini üst sınırı |
| `input` | `max-bytes` | 5 MiB | Toplam değil, her ek dosya için byte sınırı |
| `output` | `max-token` | Sınır yok | Sağlayıcıya gönderilen çıktı token sınırı |
| `connection` | `provider` | Boş | Sağlayıcı türü; şu an `openrouter` |
| `connection` | `model` | Boş | Sağlayıcının model kimliği |
| `connection` | `key` | `OPENROUTER_API_KEY` | API anahtarını içeren ortam değişkeninin adı |

`policy = 2001` mevcut bir Policy kaydına bağlanır. Alternatif olarak politika doğrudan Agent içinde tanımlanabilir:

```xaf
agent {
    id = 1002
    name = "Inline Research Agent"
    policy {
        access {
            agent
        }
        action {
            read = true
        }
    }
}
```

İki yöntem aynı Agent içinde birlikte kullanılamaz. `policy = ...` ile inline `policy {}` seçeneklerinden biri seçilmelidir.

### Zamanlama semantiği

`delay`, her HTTP denemesinin kendi zaman aşımıdır. `timeout`, denemeler ve tekrar beklemeleri dahil tüm çağrının toplam süresidir. `retry.count = 3`, ilk istek başarısız olduktan sonra en fazla üç yeni deneme yapılabileceği anlamına gelir. `retry.duration`, bu denemeler arasındaki beklemedir. Toplam `timeout` dolarsa tekrar planı kesilir.

### Token sınırları ve bağlantı güvenliği

`input.max-token` yerel bir tahmindir: UTF-8 metin uzunluğundan yaklaşık hesaplanır; kullanılan modelin gerçek tokenizer'ıyla birebir aynı olmayabilir. Görsel token tüketimi bu tahmine dahil değildir. `output.max-token` sağlayıcı API'sine `max_tokens` olarak iletilir.

`connection.key` gizli anahtarın kendisi değildir. Yalnızca işletim sistemi ortam değişkeninin adıdır; gerçek anahtar XAF dosyasına yazılmaz. Şu an canlı Agent sağlayıcısı olarak yalnızca OpenRouter uygulanmıştır.

`security.container = true` Linux user/mount/PID/UTS/IPC/network namespace + chroot tabanlı gerçek bir process/filesystem sandbox başlatır. Project root salt okunur bağlanır; process ve mount alanları ayrıdır. Ağ namespace içinde izole edilir; yalnızca host tarafındaki allowlist proxy üzerinden `openrouter.ai:443` erişimine izin verilir. Host user namespace desteği yoksa `A035` döner; runtime yalıtımsız çalışmaya geri düşmez. Android/Termux üzerinde namespace yetenekleri cihaza/ROM'a bağlıdır.

## 5. `config.observer`

Observer'ın neyi izleyeceği `.sph` içinde, o gözlemin çalışma ve kayıt ayarları ise XAF içindeki `config.observer` profilinde tutulur. Profil anahtarı SPH Observer `id` değeriyle aynı sayısal ID olmalıdır.

SPH tarafındaki örnek:

```sph
use { observer }
state status = "ready"
observer {
    id = 1001
    source = self
    watch {
        status
    }
}
```

Aynı Observer için XAF profili:

```xaf
config {
    observer {
        1001 {
            watch = true
            log = true
            path = "logs"
            level = detailed
            action {
                read = true
                modify = true
                create = true
                remove = false
                reorder = false
            }
        }
    }
}

policy {
    id = 2001
    access {
        observer
        source {
            self = true
            external = false
        }
    }
    action {
        read = true
    }
}
```

| Alan | Zorunluluk | İşlev |
|---|---|---|
| `watch` | Zorunlu boolean | Gözlemciyi açar veya kapatır |
| `log` | Zorunlu boolean | Günlük JSON kayıtlarının yazılıp yazılmayacağını belirler |
| `path` | Zorunlu | `log = true` iken klasör yolu; `false` iken `null` |
| `level` | `log = true` iken zorunlu | `compact`, `normal`, `detailed`, `debug` |
| `action` | Zorunlu | Kayda alınacak değişim türleri |

`action.read`, gözlem kayıtlarının üretilmesine izin verir. `create`, `modify`, `remove` ve `reorder` ise değişim listesindeki ilgili olay türlerini filtreler. `watch = true` ve `log = false` iken günlük JSON dosyası yazılmaz; sonraki farkı hesaplayabilmek için dahili `.sophon/snapshots/<id>.json` anlık görüntüsü güncellenir.

`path`, `log = true` olduğunda boş olamaz; mutlak yollar ve `..` içeremez (`X116`).
Çalışma anında yol sembolik bağlantılar da çözülerek proje içinde tutulur; proje
kökü dışına çıkan bağlantılar `F012` ile reddedilir. Dahili `.sophon/snapshots`
yolu da aynı sınır kontrolünden geçer.

`source` ayarı Observer profilinde değil, onu yöneten politikanın `access.source` bloğundadır. SPH'de `source = self` mevcut dosyayı, `source = "other.sph"` harici bir dosyayı seçer. XAF `access.source` ise hangi kaynak sınıfına izin verildiğini söyler:

- `self = true`: aynı SPH dosyasının izlenmesine izin.
- `external = true`: başka SPH dosyalarının izlenmesine izin.

İki izin birbirinden bağımsızdır ve yazılmadıklarında `false` kabul edilir. Ayrıca Observer kullanımı için `access.observer` ve `action.read` de verilmelidir.

`features { self-observation = true }` özelliği, daha önce tanımlanmış özel tüm-dosya gözlemi mekanizmasıdır ve XAF kökünde kalır; `config.observer` profili onun yerine geçmez.

## 6. `config.database`

```xaf
config {
    database {
        connection {
            provider = "local"
        }
        max-records = 100000
        max-bytes = 52428800
    }
}
```

- `connection.provider` şu an yalnızca `local` olabilir.
- Her `.svt` dosyasının yolu SPH içindeki ilgili database bağlantısında tanımlanır.
- `max-records`, bir vault içinde tutulabilecek en fazla kayıt sayısıdır.
- `max-bytes`, `.svt` dosyasının byte cinsinden üst sınırıdır; kayıt değişikliğinden önce ve sonra kontrol edilir.
- Veritabanına erişmek için `policy.access.database`, yapılacak işlem için ilgili `policy.action` izni gerekir.
- SPH içindeki `connect = file.svt` yolu proje köküne göre çözülür; proje dışına çıkan mutlak/`..`/sembolik bağlantılar `F010` veya `F012` ile reddedilir.
- Kayıt güncellemesi atomik dosya değişimiyle yazılır; değiştirme başarısız olursa önceki `.svt` korunur (`V015`).

## 7. `config.file-system`

```xaf
config {
    file-system {
        allowed_path { "data" "output" }
        forbidden_path { "data/private" "secrets" }
        action {
            file { create read modify move copy delete }
            folder { create read modify move copy delete zip-unzip }
        }
    }
}
```

`allowed_path` zorunludur ve en az bir proje-relative klasör/yol içermelidir. Mutlak yollar ve `..` kabul edilmez. `forbidden_path`, izinli bir dizinin içinde olsa bile önceliklidir. `action.file` ve `action.folder` ayrıntılı dosya/klasör eylemlerini belirler.

Bir dosya işleminde üç kontrol birlikte uygulanır: `policy.access.file-system`, `config.file-system` yol/eylem kuralları ve `policy.action`. Örneğin SPH dosyasındaki `write` işlemi için politika `action.write = true` olmalı, `config.file-system.action.file` içinde de `modify` bulunmalıdır.

Agent ek dosyaları da dosya okuma olarak değerlendirilir. V2'de `access.input` yoktur; ek dosya erişimi `access.file-system`, `config.file-system` ve `action.read` ile sınırlandırılır. Kullanıcıdan alınan metin mesajı ise ayrı bir XAF erişim kaynağı değildir. `input.max-token` ve `input.max-bytes` erişim izni değil, Agent girdi sınırlarıdır.

## 8. `config.execute`

```xaf
config {
    execute {
        file {
            "worker.sph"
            "processor.sph"
        }
        command { }
    }
}
```

`file` yalnızca çalıştırılmasına izin verilen `.sph` dosyalarının proje-relative yol listesidir. Bir SPH programının `execute { file = "worker.sph" }` çağrısı için hem `policy.access.execute` hem de bu izin listesinde dosyanın bulunması gerekir. `command` bloğu şu an boş kalır: çalışma zamanında kayıtlı Sophon komutu bulunmamaktadır. Sophon komutları hiçbir zaman işletim sistemi shell'ine aktarılmaz.

## 9. `policy` — erişim ve işlem izinleri

```xaf
policy {
    id = 2001
    access {
        multi
        observer
        database
        file-system
        execute
        agent
        component
        source {
            self = true
            external = false
        }
    }
    action {
        read = true
        write = true
        modify = true
        remove = false
        create = true
        reorder = false
    }
}
```

`access` altında yalnızca aşağıdaki yedi kaynak yeteneği yazılabilir:

| Anahtar | Anlamı |
|---|---|
| `multi` | `config.multi` içinde etkinleştirilen multi bileşenleri |
| `observer` | Observer kullanımı |
| `database` | Sophon Vault erişimi |
| `file-system` | Dosya/klasör işlemleri ve Agent ek dosyaları |
| `execute` | Başka `.sph` programlarını çalıştırma |
| `agent` | Agent çağırma ve kullanma |
| `component` | `component { ... }` gruplarını kullanma |

İstek içinde altı değil yedi yetenek listelenmiştir; uygulanan şema bu yedi anahtarı kabul eder. Bunlar çıplak şekilde yazılır; değer veya alt blok almazlar. Bilinmeyen erişim anahtarları reddedilir. `state`, `multi-state`, `surface`, `ask` ve `input` v2 `access` alanına yazılmaz. State ve olağan bileşenler normal dil özellikleridir; normal `surface` ve `ask` kullanımı ayrıca izin gerektirmez. Multi ailesi ise `multi` iznine ve `config.multi` etkinleştirmesine tabidir.

### `access.source`

`source` alt bloğu yalnızca `self` ve `external` boolean alanlarını alır. Şu anda bu kaynak sınıfı izinleri Observer'ın mevcut SPH dosyasını mı yoksa harici bir SPH dosyasını mı izlemesine izin verildiğini denetler.

### `action`

`action` alanları boolean izinlerdir. Bir kaynağa erişim verilmiş olması, o kaynakta her işlemin serbest olduğu anlamına gelmez.

| Alan | Anlam |
|---|---|
| `read` | Okuma ve gözlem kayıtları |
| `write` | Yeni veri/dosya içeriği yazma |
| `modify` | Mevcut içeriği değiştirme, taşıma/kopyalama gibi işlemler |
| `remove` | Silme |
| `create` | Yeni dosya/kayıt/klasör oluşturma |
| `reorder` | Sıralamayı değiştirme |

Eksik veya `false` olan izin reddedilir. Database işlemlerinde `write`, `modify`, `remove`, `read` ilgili database komutuyla eşleşir. Dosya işlemlerinde yüksek seviye `policy.action` denetimi ile `config.file-system.action` ayrıntılı denetimi birlikte uygulanır. Agent çağrısı `access.agent` ve `action.read` gerektirir; Agent'ın ayrıca `permission.execute = true` ayarı olmalıdır.

### `deny` — miras alınan izinleri iptal etme

```xaf
policy {
    id = 2000
    access { multi observer }
    action { read = true }
}
policy {
    id = 2001
    inherits {
        id = 2000
        deny {
            access { multi source { external = true } }
            action { read = true }
        }
    }
}
```

Deny kullanılmayacaksa kısa biçim korunur: `inherits = 2000`. İptal kuralı
bulunacaksa `inherits` bir bloğa dönüşür; üst politika `id` ile belirtilir ve
`deny` bu bloğun içine yazılır. `deny.access` altında listelenen yetenekler ve
`deny.access.source` alanları üst politikadan miras alınmış olsa bile kapatılır.
`deny.action` içinde `true` yazılan eylem reddedilir. Deny-overrides kuralı tüm
alt politika zincirinde korunur; daha aşağıdaki bir `access` veya `action` grant'i
bu reddi kaldıramaz.

## 10. Policy kalıtımı

Deny içermeyen miras için `inherits = 2000` kullanılır. Miras alınan izinleri
sınırlamak gerekiyorsa `inherits { id = 2000 deny { ... } }` kullanılır. Döngüsel
veya bulunamayan üst politika reddedilir. Erişim izinleri üst ve alt politikalardan
birleştirilir; deny kararı bu birleşimden daha yüksek önceliğe sahiptir. Önceki v2
sürümlerindeki kök düzey `deny {}` biçimi geçiş uyumluluğu için okunur; yeni dosyalarda
`deny` yalnızca `inherits` içine yazılmalıdır.

## 11. Yetkilendirme özeti

- `multi`: `access.multi` + kullanılan bileşen adının `config.multi` içinde olması.
- `observer`: `access.observer` + uygun `access.source` + `action.read` + aynı ID'li `config.observer` profili.
- `database`: `access.database` + ilgili `action` izni + gerekiyorsa `config.database` sınırları.
- `file-system`: `access.file-system` + izinli yol/eylem + global `action`.
- `execute`: `access.execute` + `config.execute.file` izin listesi (komutlar henüz kayıtlı değil).
- `agent`: `access.agent` + `action.read` + Agent kaydında `permission.execute = true` + geçerli `connection`.
- `component`: `access.component`.

## 12. Geçiş notları ve uygulanmamış noktalar

- Yeni şema sayısal Agent, Policy ve Observer kimliklerini kullanır; eski ad tabanlı Agent/Policy biçimleri yalnızca geriye dönük uyumluluk için tutulur.
- Eski Observer profili kök `observer { ... }` biçiminden yeni `config.observer { ... }` biçimine taşınmalıdır.
- Eski `access.input`, `access.state`, `access.multi-state`, `access.surface` ve `access.ask` anahtarları yeni v2 politikalarında kabul edilmez.
- `security.container = true` Linux user/mount/PID/UTS/IPC namespace ve chroot tabanlı sandbox kullanır; ağ namespace içinde izole edilir ve yalnızca `openrouter.ai:443` allowlist proxy çıkışına izin verilir. Android/Termux desteği host namespace yeteneklerine bağlıdır.
- Canlı Agent sağlayıcısı OpenRouter ile sınırlıdır.
- Token sayımı yerel tahmindir; görsel token tüketimini kapsamaz.
- `config.execute.command` bilerek boştur; henüz komut kaydı yoktur.
