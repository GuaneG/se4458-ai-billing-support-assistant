# SE4458 Grup 2 demo videosu

**Proje** AI Billing Support Assistant  
**Hedef süre** Yaklaşık 6 dakika  
**Kayıt sırası** Mimari → Gateway ve yetki → üç Chat senaryosu → simüle ödeme → testler ve teslim dosyaları

Konuşma metnini olduğu gibi okuyabilir veya kendi cümlelerinle anlatabilirsin. Zamanlar yaklaşık. Yanıt beklenen kısımları kurguda kısaltabilirsin.

## Kayda girmeden önce

1. Gateway yenilenmiş bir tarayıcı sekmesinde açılsın ve `A001` ile giriş yapılabilsin. Parolayı kayıttan önce gir.
2. Üç pencereyi hazırla. [Öğrenme rehberi](AWS_OGRENME_REHBERI.html), canlı Chat ve PowerShell. PowerShell’de proje kökü, GitHub/IDE’de teslim dosyaları hazır olsun.
3. Ekim faturasının **güncel kalan borcunu** önceden oku. Son doğruladığımız toplam **80 dolar**, ödenen **20 dolar**, kalan **60 dolar** idi. Yeni kayıtta **10 dolarlık** simüle ödeme kullanırsan bu başlangıçla **60 → 50 dolar** beklersin. Ekran farklı bir başlangıç gösterirse o tutar üzerinden anlat. Borç sıfırsa, önceki **80 → 60 dolar** onay kanıtını göster.
4. Üç MCP sorgusunun ve test çalıştırma talimatının olduğu README bölümünü açık bırak. Token, parola, API key ve secret dosyalarının göründüğü sekmeleri kapat.

## 0:00–0:40 · Giriş ve mimari

**Ekranda:** Öğrenme rehberinde mimariyi aç. Sırayla tarayıcı, API Gateway, EC2 içindeki Chat/Agent, Billing, MCP ve PostgreSQL’i göster.

> Merhaba, ben Can. SE4458 Grup 2 midterm projem bir mobil fatura asistanı. Abone faturasını sorgulayabiliyor, tarifesini öğrenebiliyor ve açık onayla simüle ödeme yapabiliyor. Uygulamayı AWS’de tek bir EC2 üzerinde çalıştırdım. Tarayıcı Chat’e API Gateway üzerinden ulaşıyor. Cloud Map, Chat ve Billing’in private IP ve portunu veriyor. Gateway, EC2’ye VPC Link üzerinden bağlanıyor. Agent, tarifeyi aynı EC2’deki MCP’den, kayıtlı fatura verisini ise Gateway üzerinden Billing REST API’den alıyor.

**Ekranda kalması gereken kanıt:** Chat için port **8002**, Billing için **8000**, MCP için **loopback 8001**. Agent’ın Billing isteğinin aynı Gateway’e döndüğünü gösteren hat.

## 0:40–1:30 · İki route ve korumalı endpoint

**Ekranda:** PowerShell’de aşağıdaki [Gateway kontrolünü](#gateway-kontrolü-için-powershell) çalıştır veya önceden kaydettiğin temiz çıktıyı göster. Aynı Gateway’de fatura özeti ve fatura detayı route’larını belirt.

> İki versioned route örneği göstereceğim. İlk route, demo verisi olarak işaretlenen Ekim özeti için token olmadan 200 dönüyor. İkinci route fatura detayı. Aynı Gateway URL’sinde detay JWT’siz çağrıldığında 401, abonenin kendi JWT’siyle çağrıldığında 200 dönüyor. İstekte ikinci sayfayı ve sayfa başına bir kalemi istedim. Sonuçta page, pageSize ve totalItems alanlarını görebiliyoruz.

**Ekranda kalması gereken kanıt:** Özet `200`, detay tokensız `401`, detay sahibiyle `200`, `page=2`, `pageSize=1` ve `totalItems=2`. Parola ve token değerleri çıktıdan gizli kalır.

## 1:30–3:15 · Üç Chat senaryosu

Her sorudan sonra **Tool trace** kartını aç. Hangi tool’un çalıştığı görünsün. Birleşik senaryoda **Agent ↔ LLM** sekmesini kısa süre açıp tool seçimi ile sonucunun modele dönüşünü göster.

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

## 4:10–4:35 · Operatör işlemleri

**Ekranda:** Operatör ekranı veya önceden aldığın Kasım test çıktısı. Add Usage ve Calculate Bill seçeneklerini kısa göster.

> Operatör panelinde iki ayrı işlem var. Add Usage seçilen aya on dakika veya bir megabayt ekliyor. Calculate Bill, biriken kullanımı alıp aynı aya ait faturayı hesaplıyor. Kasım testinde yeni kullanım elli dakikaya çıkmıştı, kayıtlı fatura kırk dakika gösteriyordu. Hesaplamayı onaylayınca faturadaki kullanım da elli dakika oldu. İlk bin dakika pakete dahil olduğu için toplam 50 dolar kaldı.

## 4:35–5:35 · Üç MCP retrieval ve otomatik testler

**Ekranda:** [README’deki üç MCP sorgusunu](../README.md#mcp-billing-guide) aç, sonra terminalde MCP testini çalıştır. Üç testin çıktısı ekranda kalırken tam suite komutunu göster.

> MCP’de üç ayrı sorguyu test ettim. Ek internet için 3.2, kısmi ödeme için 5.1 ve vade sonrası hizmet kısıtlaması için 6.3 bölümleri dönüyor. Testler araç çağrısını MCP SDK’nın Streamable HTTP protokolü üzerinden yapıyor. Tam test paketi ayrıca beş Billing işleminin başarı ve hata senaryolarını kontrol ediyor. Testleri yerelde pytest ile çalıştırabiliyorum.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -v 'tests/test_mcp_billing_guide.py' -k 'relevant_billing_section and (3.2 or 5.1 or 6.3)'
& '.\.venv\Scripts\python.exe' -m pytest -q
```

**Ekranda kalması gereken kanıt:** Üç retrieval testinin sonucu ve tam suite’in gerçek özeti. PostgreSQL test ortamı hazırlanmadıysa `skipped` görünen kontrolleri geçmiş olarak anlatma. Önceki tam PostgreSQL test kanıtı [yerel kanıt dosyasında](LOCAL_DEMO_EVIDENCE.md#protected-route-and-tests).

## 5:35–6:00 · Teslim dosyaları

**Ekranda:** README ve bağlantıları. OpenAPI, ER diyagramı, MCP tool şeması, deploy/route tablosu, testler ve demo kanıtları.

> README’de canlı Gateway adresi, route eşlemeleri ve hocanın denemesi için adımlar var. Billing ve Chat OpenAPI sözleşmelerini, PostgreSQL ER diyagramını, MCP tool şemasını ve test kanıtlarını da aynı repoya ekledim.

Bu kapanış metnindeki dosyaları ve canlı URL’yi kayıttan önce README’de kontrol et.

## Gateway kontrolü için PowerShell

İlk satır çalışınca Gateway’in **Invoke URL** değerini gir. Parola sorusu maskeli. Çıktıda HTTP durumları ve sadece seçilen fatura alanları görünür.

```powershell
$demoGatewayUrl = (Read-Host 'Gateway Invoke URL').TrimEnd('/')
$demoBillPath = '/api/v1/subscribers/A001/bills/2026/10'
$demoDetailUrl = "$demoGatewayUrl$demoBillPath/details?page=2&pageSize=1"

curl.exe -sS -o NUL -w "Summary HTTP %{http_code}\n" "$demoGatewayUrl$demoBillPath"
curl.exe -sS -o NUL -w "Detail without JWT HTTP %{http_code}\n" "$demoDetailUrl"

$demoPassword = Read-Host 'A001 demo parolası' -AsSecureString
$demoCredential = [pscredential]::new('A001', $demoPassword)
$demoLoginBody = @{
    username = 'A001'
    password = $demoCredential.GetNetworkCredential().Password
} | ConvertTo-Json -Compress
try {
    $demoSession = Invoke-RestMethod -Method Post -Uri "$demoGatewayUrl/api/v1/auth/login" -ContentType 'application/json' -Body $demoLoginBody -ErrorAction Stop
    $demoHeaders = @{ Authorization = "Bearer $($demoSession.token)" }
    $demoDetail = Invoke-WebRequest -UseBasicParsing -Uri $demoDetailUrl -Headers $demoHeaders -ErrorAction Stop
    "Detail with owner JWT HTTP $($demoDetail.StatusCode)"
    $demoDetail.Content | ConvertFrom-Json | Select-Object total, paidAmount, remainingBalance, page, pageSize, totalItems
} finally {
    Remove-Variable demoPassword, demoCredential, demoLoginBody, demoSession, demoHeaders -ErrorAction SilentlyContinue
}
```

## Kayıt tamamlandığında

- Videodaki Gateway `200 / 401 / 200` ekranını, üç Agent senaryosunu ve onaylı ödeme sonucunu README’deki kanıtlara bağla.
- MCP retrieval çıktısında üç ayrı bölüm numarası görünsün. Pytest özetiyle birlikte sakla.
- Video bağlantısını hocanın kullanacağı erişimle açmayı dene.
