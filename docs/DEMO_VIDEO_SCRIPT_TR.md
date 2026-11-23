# SE4458 Grup 2 demo videosu

**Proje** AI Billing Support Assistant  
**Hedef süre** Yaklaşık 6,5 dakika

**Kayıt sırası** Mimari → Gateway ve yetki → üç Chat senaryosu → simüle ödeme → testler ve teslim dosyaları

Konuşma metnini olduğu gibi okuyabilir veya kendi cümlelerinle anlatabilirsin. Zamanlar yaklaşık. Yanıt beklenen kısımları kurguda kısaltabilirsin.

## Kayda girmeden önce

1. Gateway yenilenmiş bir tarayıcı sekmesinde açılsın ve `A001` ile giriş yapılabilsin. Parolayı kayıttan önce gir.
2. [Öğrenme rehberini](AWS_OGRENME_REHBERI.html), canlı Chat’i ve iki PowerShell oturumunu hazırla. EC2’ye SSH ile bağlı oturumda açılış için servisleri göster. Gateway ve pytest komutlarını bilgisayarındaki PowerShell’de çalıştır.
3. Ekim faturasının **güncel kalan borcunu** önceden oku. Son doğruladığımız toplam **80 dolar**, ödenen **20 dolar**, kalan **60 dolar** idi. Yeni kayıtta **10 dolarlık** simüle ödeme kullanırsan bu başlangıçla **60 → 50 dolar** beklersin. Ekran farklı bir başlangıç gösterirse o tutar üzerinden anlat. Borç sıfırsa, önceki **80 → 60 dolar** onay kanıtını göster.
4. Üç MCP sorgusunun ve test çalıştırma talimatının olduğu README bölümünü açık bırak. Token, parola, API key ve secret dosyalarının göründüğü sekmeleri kapat.

## 0:00–0:40 · Giriş ve mimari

**Ekranda:** Önce EC2’ye SSH ile bağlı olduğun PowerShell terminalinde çalıştır. Üç servisin adı ve çalışma durumu ekranda görünsün. Ardından mimari rehberine geç.

```bash
systemctl list-units 'se4458@*.service' --type=service --no-pager
```

> Merhabalar hocam, ben Can. Grup 2’deydim. Projem bir mobil fatura asistanı. Abone faturasını sorgulayabiliyor, tarifesini öğrenebiliyor ve onay butonuyla deneme amaçlı ödeme yapabiliyor.
>
> Uygulama AWS’de tek bir EC2 instance’ında çalışıyor. Burada Chat API, Billing REST API ve MCP Server olmak üzere üç servis var. Verileri de aynı EC2’de bir Docker container’ında çalışan PostgreSQL’de saklıyoruz.
>
> Tarayıcı sohbet arayüzünü açmak için API Gateway’e istek gönderiyor. Gateway, Cloud Map’ten Chat API’nin private IP adresini ve portunu bulup VPC Link üzerinden isteği iletiyor. Agent tarife kurallarını aynı EC2’deki MCP Server’dan alıyor. Kayıtlı fatura verisi gerektiğinde ise aynı Gateway’e tekrar istek gönderiyor ve Gateway bu kez Billing REST API’ye yönlendiriyor.

**Ekranda kalması gereken kanıt:** Chat için port **8002**, Billing için **8000**, MCP için **loopback 8001**. Agent’ın Billing isteğinin aynı Gateway’e döndüğünü gösteren hat.

## 0:40–1:30 · İki route ve korumalı endpoint

**Ekranda:** İstersen önce [PowerShell scriptini](../scripts/demo-gateway-check.ps1) açıp üstteki özet ve detay URL’lerini göster. Ardından [Gateway kontrolünü](#gateway-kontrolü-için-powershell) çalıştır. Özet ve detay çıktılarındaki alanları karşılaştır.

> Hazırladığımız PowerShell scriptiyle API Gateway üzerinden A001 müşterisinin Ekim 2026 faturasını sorguluyorum. İlk istekte özet endpoint’ine JWT göndermiyorum. Bu demo özeti açık olduğu için 200 alıyorum. Yanıtta toplam tutarı, ödenen tutarı, kalan borcu ve ödeme durumunu görüyoruz.
>
> Ardından aynı faturanın detayını istiyorum. Detay endpoint’i korumalı olduğu için JWT’siz istek 401 dönüyor. Script A001 olarak giriş yapıp aldığı JWT’yi aynı isteğe ekleyince 200 alıyorum.
>
> Detay yanıtında tutarların yanında telefon ve internet kullanımı ile ücret dökümü de geliyor. İkinci sayfayı ve sayfa başına bir ücret kalemini istediğim için iki kalemden yalnızca biri bu yanıtta görünüyor. Burada pagination’ın çalıştığını görüyoruz.

**Ekranda kalması gereken kanıt:** Özet `200`, detay tokensız `401`, detay sahibiyle `200`. Özet JSON’unda tutarlar ve durum, detay JSON’unda kullanım, `chargeBreakdown`, `page=2`, `pageSize=1`, `totalItems=2` ve `returnedItems=1` görünsün. Parola ve token değerleri çıktıdan gizli kalır.

## 1:30–3:15 · Üç Chat senaryosu

Her sorudan sonra **Tool trace** kartını aç. Birleşik senaryoda `query_bill_details` ve `search_billing_documentation` satırlarını genişletip tool parametrelerini ve dönen sonuçları göster. AWS'de `CHAT_INCLUDE_DIALOGUE=true` açıksa **Agent ↔ LLM** sekmesine geç. Modelin istediği tool ile Agent'ın döndürdüğü sonucu aynı `call_id` üzerinden göster.

| Soru | Ekranda göster | Konuşma metni |
|---|---|---|
| **20 GB paketimi 1 GB geçersem kaç dolar ek ücret öderim?** | Yalnız `search_billing_documentation`, §3.2 ve 10 dolar ek ücret | “Bu soru bir tarife kuralı. Model rehber aramasını seçti. Ek kullanımın başladığı her on gigabaytlık blok on dolar. Bir gigabayt aşım, bir ek blok sayılıyor.” |
| **Ekim 2026 faturam kaç dolar, ne kadar borcum kaldı?** | Yalnız `query_bill`, kayıtlı 80 dolar toplam ve o anki kalan borç | “Bu kez kullanıcının kendi faturasını soruyorum. Agent, Billing REST API üzerinden kayıtlı toplamı ve güncel bakiyeyi getiriyor.” |
| **Ekim 2026’da internet paketimi kaç GB aştım ve faturada neden 70 dolar internet ücreti var? Rehber bölümünü belirt.** | `query_bill_details` + `search_billing_documentation`, 35 GB kullanım, 15 GB aşım, §3.1–3.2 | “Model iki kaynağa ihtiyaç duydu. Billing’den gerçek kullanım 35 gigabayt. Rehberden ilk 20 gigabaytın fiyatı 50 dolar. Aşılan 15 gigabayt iki ek bloğa giriyor. İnternet ücreti 50 artı 20, yani 70 dolar.” |

Üçüncü senaryoda kısa geçiş cümlesi:

> Model tool’u seçiyor. HTTP ve MCP çağrılarını Agent yürütüyor. Tool sonucu modele dönüyor, model de hesabı ve kaynağı kullanıcıya açıklıyor.

## 3:15–4:10 · Açık onayla simüle ödeme

**Ekranda:** Ayrı sekmede özet ve mevcut bakiye. Chat’e **“Ekim 2026 faturama 10 dolar öde.”** yaz. Sağda `prepare_bill_payment`, solda ödeme kartı görünsün.

> Chat, onay bekleyen 10 dolarlık taslağı hazırladı. Özet sekmesini yenileyince borç hâlâ aynı. Şimdi butona basıp işlemi onaylıyorum.

**Ekranda:** **Ödemeyi onayla** butonuna bir kez bas. Onaylandı yazısını göster ve özet sekmesini yenile.

> Billing simüle ödemeyi kaydetti. Ödenen tutar 10 dolar arttı, kalan borç 10 dolar azaldı. Fatura toplamı 80 dolar olarak kaldı.

**Ekranda kalması gereken kanıt:** Aynı ay için **onay öncesi → onay → onay sonrası**. Önceki kaydı kullanırsan, gösterdiğin tutar **80 → 60 dolar** ve ödeme **20 dolar**.

## 4:10–5:10 · Canlı operatör işlemleri

**Ekranda:** Canlı uygulamayı ayrı bir gizli pencerede operatör hesabıyla aç. Kasım 2026’yı kullan. Böylece Ekim fatura ve ödeme örneğini ayrı tutarsın.

1. **Başlangıcı göster.** EC2 terminalinde aşağıdaki sorguyu çalıştır. `current_minutes` birikmiş kullanımı, `billed_minutes` kayıtlı faturadaki kullanımı, `total_usd` fatura toplamını gösterir.
2. Operatör ekranında **Kullanım ekle (Add Usage)** seç. Abone `A001`, yıl `2026`, ay `11`, kullanım türü **Telefon (+10 dakika)**. **İşlemi hazırla → Onayla ve uygula**. **Kullanım kaydedildi** mesajını göster.
3. **Aynı sorguyu tekrar çalıştır.** Güncel kullanım 10 dakika artar. Kayıtlı faturadaki dakika ve tutar aynı kalır.
4. Operatör ekranında **Fatura hesapla (Calculate Bill)** seç. Aynı abone ve dönem için **İşlemi hazırla → Onayla ve uygula**. **Fatura hesaplandı ve kaydedildi** mesajını göster.
5. **Sorguyu son kez çalıştır.** Faturadaki dakika, güncel kullanımla eşleşir. 60 dakika pakete dahil olduğu için toplam 50 dolar kalır.

> Başlangıçta hem güncel kullanım hem de faturadaki kullanım elli dakika. On dakika ekleyince güncel kullanım altmışa çıkıyor, faturada hâlâ elli dakika görünüyor. Faturayı yeniden hesapladığımda faturadaki dakika da altmış oluyor. Paket sınırının içinde kaldığımız için toplam elli dolar.

**Beklenen karşılaştırma:** 23 Kasım’da kontrol ettiğimiz başlangıç `50 / 50 / 50.00` idi. Bunun üzerine ilk işlem `60 / 50 / 50.00`, ikincisi `60 / 60 / 50.00` verir. Prova sırasında kullanım eklediysen konuşmayı ekrandaki güncel sayılara göre yap.

**Üç ölçüm için kullanacağın PostgreSQL sorgusu.**

```bash
cd "$HOME/se4458"
sudo docker compose -f compose.yaml -f compose.aws.yaml exec -T postgres \
  psql -U billing -d billing_dev -c "
    SELECT u.phone_minutes AS current_minutes, b.phone_minutes AS billed_minutes,
           round((b.phone_charge_cents + b.internet_charge_cents) / 100.0, 2) AS total_usd
    FROM monthly_usage u
    LEFT JOIN bills b USING (subscriber_no, bill_year, bill_month)
    WHERE u.subscriber_no = 'A001' AND u.bill_year = 2026 AND u.bill_month = 11;"
```

## 5:10–6:10 · Üç MCP retrieval ve otomatik testler

**Ekranda:** [README’deki üç MCP sorgusunu](../README.md#mcp-billing-guide) aç, sonra terminalde MCP testini çalıştır. Üç testin çıktısı ekranda kalırken tam suite komutunu göster.

> MCP’de üç ayrı sorguyu test ettim. Ek internet için 3.2, kısmi ödeme için 5.1 ve vade sonrası hizmet kısıtlaması için 6.3 bölümleri dönüyor. Testler araç çağrısını MCP SDK’nın Streamable HTTP protokolü üzerinden yapıyor. Tam test paketi ayrıca beş Billing işleminin başarı ve hata senaryolarını kontrol ediyor. Testleri yerelde pytest ile çalıştırabiliyorum.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -v 'tests/test_mcp_billing_guide.py' -k 'relevant_billing_section and (3.2 or 5.1 or 6.3)'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

**Ekranda kalması gereken kanıt:** Üç retrieval testinin sonucu ve tam suite’in gerçek özeti. PostgreSQL test ortamı hazırlanmadıysa `skipped` görünen kontrolleri geçmiş olarak anlatma. Önceki tam PostgreSQL test kanıtı [yerel kanıt dosyasında](LOCAL_DEMO_EVIDENCE.md#protected-route-and-tests).

## 6:10–6:35 · Teslim dosyaları

**Ekranda:** README ve bağlantıları. OpenAPI, ER diyagramı, MCP tool şeması, deploy/route tablosu, testler ve demo kanıtları.

> README’de canlı Gateway adresi, route eşlemeleri ve hocanın denemesi için adımlar var. Billing ve Chat OpenAPI sözleşmelerini, PostgreSQL ER diyagramını, MCP tool şemasını ve test kanıtlarını da aynı repoya ekledim.

Bu kapanış metnindeki dosyaları ve canlı URL’yi kayıttan önce README’de kontrol et.

## Gateway kontrolü için PowerShell

Proje klasöründen [Gateway kontrol scriptini](../scripts/demo-gateway-check.ps1) çalıştır. Script proje için kullanılan **Invoke URL**’yi otomatik seçer ve maskeli A001 parolasını ister. Çıktıda HTTP durumları, seçilen fatura alanları ve yanıtta kaç ücret kalemi döndüğü görünür.

```powershell
Set-Location 'C:\Projects\se4458\ai-billing-support-assistant'
& '.\scripts\demo-gateway-check.ps1'
```

## Kayıt tamamlandığında

- Videodaki Gateway `200 / 401 / 200` ekranını, üç Agent senaryosunu ve onaylı ödeme sonucunu README’deki kanıtlara bağla.
- MCP retrieval çıktısında üç ayrı bölüm numarası görünsün. Pytest özetiyle birlikte sakla.
- Video bağlantısını hocanın kullanacağı erişimle açmayı dene.
