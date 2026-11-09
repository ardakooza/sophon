# Sophon — Control Flow tasarımı ve XAF kalıtım güncellemesi

Tarih: 9 Kasım 2026

## Kullanıcı kararlarına göre yapılan güncellemeler

### 1. Control Flow sözdizimi

`if`, `else if` ve `else` yerine `decide / when / otherwise` tasarımı seçildi.

```sph
decide {
    when age ≥ 18 and verified {
        surface { "Access granted" }
    }
    when age ≥ 13 {
        surface { "Limited access" }
    }
    otherwise {
        surface { "Access denied" }
    }
}
```

İlk doğru `when` çalışır. `otherwise` isteğe bağlıdır, bir kez kullanılabilir ve son blok olmalıdır. Bu Control Flow yapısının parser/runtime uygulaması henüz yapılmadı.

### 2. Karşılaştırma yazımları

- `!=` ve `≠` aynı eşitsizlik operatörüdür.
- `>=` ve `≥` aynı büyük-eşit operatörüdür.
- `<=` ve `≤` aynı küçük-eşit operatörüdür.
- `==`, `>`, `<`, `not`, `and`, `or` da tasarıma dahildir.

ASCII ve Unicode yazımları aynı semantiğe sahiptir. Bunların Control Flow parser/runtime uygulamasıyla etkinleştirilmesi gerekir; mevcut aritmetik Expression Engine henüz boolean karşılaştırma yürütmez.

### 3. State güncelleme semantiği

Mevcut parser davranışı kullanıcı tarafından açıklanan kurala uyar hale getirildi:

```sph
state name = "arda"
state name = "elif"  // mevcut state güncellenir
```

Aynı state'e aynı değer yeniden atanırsa `S246` üretilir. Güncelleme ilk değerle belirlenen türü korur; uyumsuz tür `S242` üretir. `set name = value`, Control Flow içinde güncellemeyi açıkça belirtmek için tasarımda tutuldu; `set` parser/runtime uygulaması henüz yapılmadı.

### 4. XAF Policy inherits biçimi

Deny yoksa kısa biçim:

```xaf
policy {
    id = 2001
    inherits = 2000
}
```

Deny varsa yeni kanonik biçim:

```xaf
policy {
    id = 2001
    inherits {
        id = 2000
        deny {
            access {
                multi
                source { external = true }
            }
            action { read = true }
        }
    }
}
```

Parser bu biçimi uygular. `inherits {}` yalnızca içinde `deny {}` varsa geçerlidir. Eski v2 kök düzey `deny {}` biçimi geriye dönük uyumluluk için okunmaya devam eder; yeni dosyalarda kullanılmamalıdır. Kısa `inherits = <id>` biçimi de korunmuştur.

## Testler

- 101/101 regresyon ve entegrasyon testi başarılı.
- 54/54 `SYNTAX.md` ve `XAF_V2_SCHEMA.md` kod bloğu gerçek parser ile doğrulandı.
- 267/267 hata kodu kaynak kod ve katalog arasında eşleşiyor.
- Audit corpus senaryoları beklenen sonuçları verdi.
- Python derleme kontrolü başarılı.

Yeni testler özellikle farklı değerle state güncellemesini, aynı değer tekrarının `S246` vermesini, tür korumasını, nested `inherits { id deny }` çözümlemesini ve deny-overrides kararının alt politika zincirinde kalmasını denetler.

## Uygulanmayan / sonraki adım

Control Flow parser/runtime henüz uygulanmadı. `decide`, `when`, `otherwise`, karşılaştırma/boolean operatörleri, Unicode token eşlemesi ve `set` bu tasarım belgesine göre sonraki geliştirme aşamasında uygulanmalıdır. Bu pakette Control Flow kodlarının çalıştığı iddia edilmemektedir.
