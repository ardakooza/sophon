# Sophon Control Flow — Tasarım v3

**Durum:** `set` parser/runtime içinde uygulanmıştır. Control Flow için şimdilik yalnızca `resolve / when / otherwise` planlanmıştır; mantıksal ve karşılaştırma ifadeleri henüz parser/runtime içinde uygulanmamıştır.

Bu belge, Sophon Control Flow için esas alınacak sözdizimini tanımlar. Şimdilik tek kontrol akışı yapısı `resolve` olacaktır. `select`, `match`, `switch` ve `route` bu sürümün kapsamına dahil değildir. `if`, `else if` ve `else` anahtar sözcükleri kullanılmayacaktır.

## 1. Özgün koşul yapısı: `resolve / when / otherwise`

Koşullu dallanma `resolve` bloğu içinde tanımlanır. Her `when` bağımsız bir koşul koludur; `otherwise` isteğe bağlı varsayılan koldur.

```sph
state age = 19
state verified = true

resolve {
    when age >= 18 and verified {
        surface { "Access granted" }
    }

    when age >= 13 {
        surface { "Limited access" }
    }

    otherwise {
        surface { "Access denied" }
    }
}
```

Kurallar:

- `resolve` içinde en az bir `when` bulunmalıdır.
- `when` blokları yukarıdan aşağıya değerlendirilir; ilk doğru koşulun gövdesi çalışır.
- `otherwise` en fazla bir kez yazılabilir ve son blok olmalıdır.
- `otherwise` yoksa hiçbir koşul doğru olmadığında blok sessizce atlanır.
- Aynı `resolve` içinde iç içe `resolve` kullanılabilir.
- Boş koşul, boş `when` gövdesi veya `otherwise` sonrasında başka bir kol sözdizimi hatasıdır.
- Döngüler, `break`, `continue` ve pattern matching bu tasarımın kapsamında değildir.

## 2. Mantıksal ve karşılaştırma operatörleri

### Karşılaştırmalar

| ASCII yazımı | Unicode yazımı | Anlam |
|---|---|---|
| `==` | — | Eşit |
| `!=` | `≠` | Eşit değil |
| `>` | — | Büyük |
| `<` | — | Küçük |
| `>=` | `≥` | Büyük veya eşit |
| `<=` | `≤` | Küçük veya eşit |

ASCII ve Unicode biçimleri aynı token/işlem anlamına gelir. Unicode karakterler alternatif yazımdır; farklı bir işlem değildir. `=` atama, `==` karşılaştırmadır.

```sph
resolve {
    when age ≥ 18 and status ≠ "blocked" {
        surface { "Allowed" }
    }

    when score >= 50 and score <= 100 {
        surface { "Valid score" }
    }
}
```

### Boolean operatörleri

| Operatör | Anlam |
|---|---|
| `not` | Mantıksal değil |
| `and` | Mantıksal VE |
| `or` | Mantıksal VEYA |

```sph
resolve {
    when not banned and (verified or administrator) {
        surface { "Access granted" }
    }
}
```

### Öncelik sırası

Yüksekten düşüğe:

1. Parantez ve aritmetik ifadeler (`^`, unary `+/-`, `*`, `/`, `+`, `-`; aritmetik önceliği mevcut ifade motoruyla aynı kalır).
2. Karşılaştırmalar (`==`, `!=`/`≠`, `>`, `<`, `>=`/`≥`, `<=`/`≤`).
3. `not`.
4. `and`.
5. `or`.

Parantez önceliği açıkça değiştirebilir. `and` ve `or` kısa devreli olmalıdır: `false and X` içinde `X`, `true or X` içinde `X` değerlendirilmez.

## 3. Tip ve karşılaştırma kuralları

- Her `when` ifadesinin sonucu kesin olarak `boolean` olmalıdır. Truthy/falsy dönüşümü yapılmaz.
- `and`, `or`, `not` yalnızca boolean operand kabul eder.
- `integer` ve `float` sayısal karşılaştırmalarda birbirleriyle karşılaştırılabilir.
- `string` için `==`, `!=`/`≠` desteklenir; sıralama (`>`, `<`, `≥`, `≤`) ilk sürümde desteklenmez.
- `boolean` için yalnızca eşitlik/eşitsizlik karşılaştırmaları desteklenir.
- `null` yalnızca `== null` veya `!= null`/`≠ null` ile karşılaştırılabilir.
- Listeler ve nesneler ilk sürümde doğrudan karşılaştırılamaz.
- Farklı ve uyumsuz türler sessizce dönüştürülmez; Sophon tanısı üretilir.

## 4. State güncelleme semantiği

Sophon'da `state` yalnızca tek seferlik, değişmez bir tanım değildir. Aynı isimle gelen yeni ve farklı bir değer mevcut state'i günceller. Aynı isim ve aynı değerle yinelenen satır ise gereksiz tekrar olduğu için hata verir.

```sph
state name = "arda"
state name = "elif"  // name güncellenir
```

Aşağıdaki tekrar kabul edilmez:

```sph
state name = "arda"
state name = "arda"  // aynı değer: gereksiz tekrar hatası
```

Tür güvenliği:

- Açık tür bildiriminde (`state age: integer = 18`) sonraki değer aynı türle uyumlu olmalıdır.
- Türü çıkarılmış state'in türü ilk değerle belirlenir ve sonraki güncellemelerde korunur.
- Farklı türde değer ataması tür hatasıdır.
- Güncelleme sırasında state'in kimliği ve mevcut kapsamı korunur.

### `set` deyimi

`set name = value` mevcut bir state'i güncellemenin açık ve okunabilir biçimidir. Üst seviye programda ve fonksiyonların `execute` gövdelerinde uygulanır. `state name = value` ile aynı güncelleme semantiğine sahiptir; ancak yeni state oluşturmaz. Bu nedenle Control Flow içinde mevcut bir state'in değiştirildiğini görünür kılmak için `set` tercih edilir.

```sph
state access = false

resolve {
    when age ≥ 18 {
        set access = true
    }
    otherwise {
        set access = false
    }
}
```

`set` bilinmeyen state'i oluşturmaz. Aynı değeri yeniden atamak, `state` tekrarında olduğu gibi gereksiz tekrar hatasıdır. Çoklu state güncellemeleri mevcut `multi-state { ... }` sözdizimiyle yapılır; `set` doğrudan multi-state alanına uygulanmaz.

## 5. Kapsam ve yürütme

- `resolve` yalnızca seçilen dalın gövdesini yürütür; seçilmeyen dalların yan etkileri gerçekleşmez.
- Dış kapsamda tanımlanmış state, dal içindeki `set` veya aynı isimli farklı değerli `state` atamasıyla güncellenebilir.
- Dal içinde ilk kez tanımlanan state yerel dal kapsamındadır; dal dışına taşmaz.
- Aynı dal kapsamındaki yinelenen isimler, yukarıdaki güncelleme kurallarına tabidir.
- Fonksiyon kapsamı mevcut Functions tasarımındaki yerel kapsam ilkesini korur.

## 6. Hata tanıları için önerilen kodlar

| Kod | Durum |
|---|---|
| `S280` | `when` koşulu boolean değil |
| `S281` | `and`, `or` veya `not` boolean olmayan operand aldı |
| `S282` | Karşılaştırılamayan türler |
| `S283` | Tanımsız state/function referansı |
| `S284` | `set` ile tanımsız state güncelleme girişimi |
| `S285` | Aynı kapsamda yinelenen/aynı değerli state bildirimi |
| `S286` | Eksik veya kapanmamış `resolve`/`when` bloğu |
| `S287` | `otherwise` birden fazla veya son konumda değil |
| `S288` | `resolve` içinde `when` bulunmuyor |
| `S289` | State güncellemesinde tür uyuşmazlığı |

Kodlar uygulama sırasında mevcut hata kataloğuyla çakışma kontrolünden geçirilecek; çakışma varsa yeni boş kod aralığı seçilecektir.

## 7. Uygulama kapsamı

İlk parser/runtime sürümü şunları kapsamalıdır:

- `resolve`, bir veya daha fazla `when`, isteğe bağlı `otherwise`.
- İç içe koşul blokları.
- Boolean ve karşılaştırma ifadeleri.
- ASCII ve Unicode karşılaştırma eş anlamlıları.
- Kısa devre değerlendirmesi.
- `state` güncelleme ve `set`.
- Tip, kapsam, tekrar ve konumlu hata denetimleri.

Döngüler (`repeat`, `while` vb.), `break/continue`, `match`, exception handling ve ternary ifadeler ayrı tasarım aşamalarında ele alınacaktır.
