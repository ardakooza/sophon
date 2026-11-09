# Sophon Functions — Sözdizimi ve Çalışma Zamanı

**Durum:** Temel fonksiyon sistemi parser ve runtime tarafından uygulanmıştır.

## 1. Temel yapı

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
```

Fonksiyonlar çağrılmadan önce tanımlanmalıdır. `id` benzersiz, tırnaklı bir Sophon identifier'ıdır.

## 2. Input

- `name: type`: Zorunlu parametre.
- `name: type = value`: Default değerli; argüman atlanırsa default değerlendirilir.
- `name: type?`: Optional; atlanırsa `null` olur.
- Bir parametre hem `?` hem default alamaz.
- Zorunlu parametreler, default/optional parametrelerden önce yazılır.
- Desteklenen tipler: `string`, `integer`, `float`, `number`, `boolean`, `list`, `object`, `null`.
- Konumsal ve isimlendirilmiş argümanlar desteklenir. Aynı argüman iki kez verilemez.

```sph
state first = calculate(2, 5)
state second = calculate(a = 2, b = 5)
```

## 3. Execute ve kapsam

`execute` yalnızca fonksiyona özel yerel `state` bildirimlerini ve ifadelerini kabul eder. Yerel state'ler dışarı sızmaz; parametreler yeniden bildirilemez. Fonksiyon gövdesi çağrı anında mevcut dış state değerlerini okuyabilir; ancak dış state'leri değiştiremez. Yerel state bildirimi aynı adlı dış state'i fonksiyon kapsamı içinde gölgeler. Fonksiyonlar yan etkisiz hesaplama birimleridir.

## 4. Output

Tek sonuç:

```sph
output: integer = result
```

Çoklu sonuç:

```sph
output { sum difference }
```

Çoklu sonuç bir object/dictionary olarak döner ve alanlar `results.sum` biçiminde okunabilir.

## 5. Çağrı ve hata davranışı

- Argüman sayısı, adı ve tipi çağrı anında doğrulanır.
- Default ifadeleri, önceki parametreler bağlandıktan sonra değerlendirilir.
- İç içe fonksiyon çağrıları desteklenir.
- Çağrı derinliği 32 ile sınırlıdır.
- `sqrt()` ve sayısal operatörler kullanılabilir; `+` yalnızca sayısal toplama yapar.
- String dönüşleri ve parametreleri desteklenir; metin üretmek için `{name}` interpolation kullanılır.

Başlıca hata kodları: `S260`–`S275`. Ayrıntılar `SYNTAX.md` hata kataloğundadır.

## 6. Şimdilik kapsam dışı

`async`, `public/private`, generics, overload, `pure` bildirimi, `throws` ve cache henüz uygulanmamıştır. Recursion çağrı derinliği ile sınırlanır; koşullu dallanma henüz Control Flow tasarımına bağlıdır.
