# Sophon — Functions, Sandbox, Policy ve Control Flow Çalışma Raporu

Tarih: 9 Kasım 2026
Temel kaynak: `sophon_workspace_comprehensive_audit_20261109.zip`
Ön yedek: `sophon_workspace_backup_before_functions_sandbox_policy_20261109.zip`

## Özet

Bu geliştirme turunda üç istek uygulandı, dördüncü istek tasarım aşamasında hazırlandı:

1. Functions parser/runtime'a eklendi.
2. `security.container = true` için Linux namespace/chroot tabanlı gerçek sandbox kuruldu.
3. XAF Policy kalıtımına deny-overrides eklendi.
4. Control Flow (`if/else`, karşılaştırmalar ve mantıksal operatörler) tasarım belgesine dönüştürüldü; henüz parser/runtime'a eklenmedi.

## Test sonuçları

- 99/99 regresyon ve entegrasyon testi başarılı.
- 54/54 `SYNTAX.md` ve `XAF_V2_SCHEMA.md` kod bloğu ayrıştırıldı.
- Kaynakta bulunan 267 farklı Sophon hata kodunun tamamı dokümantasyon kataloğunda.
- Hata kataloğunda yinelenen kod bulunmadı.
- Audit corpus: 15/15 senaryo beklenen sonucu verdi: 10 çalışma senaryosu geçti, 1 Agent credential senaryosu beklenen `A021` hatasını verdi, 4 bozuk XAF senaryosu doğru hata kodlarıyla reddedildi.
- `py_compile` kontrolü `sophon.py`, `sophon_sandbox.py`, `sandbox_worker.py` ve test dosyalarında başarılı.
- Gerçek sandbox probe: PID namespace PID=1; root `/`; cwd `/workspace`; host `/etc/passwd` görünmüyor; proje mount'u salt okunur; doğrudan dış ağ erişimi kapalı.
- Container-mode Agent testi, sandbox içinden `A037` token limiti hatasını döndürdü. Gerçek OpenRouter HTTP isteği/kimlik doğrulaması bu testte yapılmadı.

## 1. Functions — uygulanan özellikler

Parser ve runtime aşağıdakileri destekliyor:

- `function { id input execute output }` tanımı.
- Benzersiz, tırnaklı identifier.
- Tipli parametreler: `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, `null`.
- Zorunlu, default (`b: integer = 10`) ve optional (`c: integer?`) parametreler.
- Konumsal ve isimlendirilmiş çağrılar.
- Parametre adı, sayısı ve tipi doğrulaması.
- Yerel state kapsamı; fonksiyon yerel değişkenleri dışarı sızmıyor.
- Çağrı anında mevcut global state'leri okuma; global state'i değiştirememe.
- Tekli typed output ve çoklu object output.
- `results.sum` biçiminde object alanı erişimi.
- İç içe çağrılar ve 32 seviye recursion sınırı.
- Editor block grammar içine `function` skeleton eklendi.

Fonksiyon gövdesinin ilk sürümünde `execute` yalnızca yerel `state` bildirimlerini kabul ediyor. Fonksiyonlar, mevcut parser mimarisi nedeniyle state ifadeleri ayrıştırılırken değerlendirilir; dolayısıyla henüz `ask`, Agent, database veya runtime sonrasında üretilen değerleri tüketen dinamik çağrı akışı sağlamaz. Control Flow ve daha sonra runtime expression değerlendirmesi bu sınırı genişletecek.

İlgili dosyalar: `sophon.py`, `FUNCTIONS_DESIGN.md`, `SYNTAX.md`, `README.md`, `audit_suite/functions.sph`.

## 2. Container isolation — uygulanan mimari

`security.container = true` artık `A035` ile doğrudan reddedilmiyor. Sophon şu izolasyonu kuruyor:

- user, mount, PID, UTS, IPC ve network namespaces;
- `chroot` ile sınırlı filesystem root;
- read-only `/workspace` project mount;
- Python runtime, shared libraries, CA/DNS dosyaları ve geçici `/tmp` dışında host filesystem mount edilmez;
- `no_new_privs` ve RLIMIT CPU, address-space, file-size, open-file, process ve core-dump sınırları;
- sandbox worker için ayrı process ve PID namespace;
- network namespace içinde dış ağ kapalı; yalnızca Unix socket CONNECT proxy üzerinden `openrouter.ai:443` egress'i.

Sandbox kurulamazsa `A035` üretilir; yalıtımsız çalışmaya fallback yoktur. Sandbox şu anda Agent provider-request sürecini izole eder. Model-generated code veya Agent tool execution henüz mevcut olmadığı için bunların yürütülmesi söz konusu değildir.

Platform sınırı: Backend Linux `unshare`, user/mount/PID/UTS/IPC/network namespace, chroot ve `/usr/bin/python3` gerektirir. Android/Termux/proot ortamları bu yetenekleri sunmayabilir; bu durumda `security.container = true` fail-closed biçimde `A035` verir. Gerçek OpenRouter bağlantısı sandbox içinden ayrıca test edilmelidir.

İlgili dosyalar: `sophon_sandbox.py`, `sandbox_worker.py`, `SANDBOX.md`, `sophon.py`, `XAF_V2_SCHEMA.md`.

## 3. Policy deny-overrides

Yeni XAF syntax:

```xaf
policy {
    id = 2001
    inherits = 2000
    deny {
        access { multi source { external = true } }
        action { read = true }
    }
}
```

Semantik:

- `deny.access` üst politikadan gelen capability grant'ini kapatır.
- `deny.access.source` self/external kaynak iznini kapatır.
- `deny.action` içinde `true` olan eylem reddedilir.
- Deny kararı alt kalıtım zincirinde kalıcıdır; daha alt bir policy aynı capability/action'ı tekrar grant etse bile deny kazanır.
- Eski ad tabanlı XAF policy kalıtımının davranışı değiştirilmedi.

`X117` hatası bozuk deny bloklarını bildirir. Runtime seviyesinde miras alınan `multi` izninin deny edilmesi de `X110` ile test edildi.

İlgili dosyalar: `sophon.py`, `SYNTAX.md`, `XAF_V2_SCHEMA.md`, `test_language_integration.py`.

## 4. Control Flow — tasarım önerisi

`CONTROL_FLOW_DESIGN.md` şu taslağı içeriyor:

```sph
if age >= 18 and verified == true {
    surface { "Access granted" }
} else if age >= 13 {
    surface { "Limited access" }
} else {
    surface { "Access denied" }
}
```

Önerilen mantıksal öncelik: `not` → karşılaştırmalar → `and` → `or`. `and/or` kısa devreli; koşul sonucu boolean olmak zorunda; truthy/falsy dönüşümü yok. Sayısal karşılaştırmalar integer/float arasında yapılabilir; string için ilk sürümde yalnızca eşitlik karşılaştırması öneriliyor.

State değişimi için açık `set state = value` deyimi önerildi. `set` kararı henüz onaylanmadığı için uygulanmadı. Dallanma scope'u, tip koruması ve hata kodları tasarım belgesinde açıklandı.

## Bilinen sınırlamalar / sonraki adımlar

1. Control Flow için `set` sözdizimi ve branch scope kararını onaylamak.
2. Functions çağrılarını parse-time yerine runtime expression evaluator'a taşımak; böylece ask/Agent/database sonuçları fonksiyonlara aktarılabilsin.
3. Agent tool execution eklenmeden önce sandbox için seccomp/cgroup hardening ve per-Agent çalışma alanı tasarlamak.
4. Gerçek OpenRouter HTTPS çağrısını sandbox proxy üzerinden staging API anahtarıyla doğrulamak.
5. Android/Termux hedefinde namespace desteğini ölçmek; destek yoksa `A035` davranışını korumak, proot'u güvenlik sandbox'ı gibi sunmamak.
6. Multi-Agent runtime ve diğer planlı standart kütüphaneler henüz uygulanmış değildir.
