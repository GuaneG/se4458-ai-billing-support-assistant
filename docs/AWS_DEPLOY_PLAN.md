# AWS deploy planı · SE4458 Grup 2

Bu plan seçilen B mimarisini yerel projeden AWS'ye taşımak için hazırlanmıştır.
Canlı URL, hesap, Region ve kaynak ID'leri kurulum sırasında doldurulur.
[Console rehberini aç](AWS_CONSOLE_GUIDE.html) · [Yerel test kanıtları](LOCAL_DEMO_EVIDENCE.md)

## 1. Mimari ve başlangıç değerleri

Tarayıcı Gateway'in HTTPS URL'sini açar. Gateway, VPC Link V2 üzerinden aynı
EC2'deki Chat ve Billing servislerine gider. AWS Cloud Map iki hedefin private IP
ve portunu bildirir. Domain, NAT Gateway ve load balancer bu tasarım için
gerekmez. EC2'nin public IPv4 adresi outbound internet ve kısıtlı SSH içindir.
Chat, OpenAI'ya HTTPS, MCP'ye loopback üzerinden Streamable HTTP ile ulaşır.
Billing REST tool çağrıları Gateway HTTPS URL'sine gider. Böylece Chat'in
dışarıdan çağrılan endpoint'leri ve Agent'ın içinden yapılan Billing REST
çağrıları aynı Gateway üzerinden izlenebilir.

| Parça | Önerilen değer | Doğrulama |
| --- | --- | --- |
| Region / VPC | Hesabında `t4g.small` ve VPC Link V2 destekleyen tek Region. EC2 ve link subnets aynı VPC'de. | Region, AZ ID ve VPC ID kontrolü |
| EC2 | Canonical Ubuntu Server 26.04 LTS **arm64** ve `t4g.small`. Public subnet, internet gateway route ve public IPv4. IMDSv2 required. Başlangıçta T4g **Standard** credit mode. | EC2 status checks geçer ve `uname -m` → `aarch64` |
| EBS | Şifreli gp3 root disk, **16 GiB öneri**. Mevcut Compose named volume bu disk üzerinde kalır. | `docker volume inspect se4458-billing_billing-data --format '{{.Mountpoint}}'` |
| `billing-host` SG | Inbound TCP 22 yalnız kendi public IPv4 `/32` adresinden. TCP 8000 ve 8002 yalnız `billing-link` SG'den. | Internetten doğrudan 8000/8002 açık değildir. |
| `billing-link` SG | Inbound kural gerekmez. Outbound TCP 8000 ve 8002 hedef `billing-host` SG. | Link `AVAILABLE`, Gateway iki servise de ulaşır. |
| Billing | `0.0.0.0:8000`, `billing_api.main:app` | EC2 içinden GET `/` ve test fatura özeti |
| Chat | `0.0.0.0:8002`, `agent.chat_api:app`, **1 worker** | EC2 içinden GET `/`, Gateway'den login ve chat |
| MCP | `127.0.0.1:8001/mcp`, `mcp_server.server:app` | Chat üzerinden rehber sorusu |
| PostgreSQL | Compose `postgres`. Host `127.0.0.1:55458` → container `5432`. | Compose `healthy` ve A001/Ekim 2026 test kaydı |

EC2 outbound erişimi Ubuntu/Docker paketleri, OpenAI ve Gateway HTTPS için
gerekir. İlk kurulumda varsayılan outbound kuralı bu trafiği karşılar. Cloud
Map kayıtlarında EC2'nin **private IPv4** adresi kullanılır. Stop/start sonrası
otomatik public IP değişebilir. EC2'nin private IP'si değişirse Cloud Map
kayıtlarını güncelle. Tek EC2 demo için tek hata noktasıdır. Ubuntu/ARM
paket kurulumu ve canlı Gateway davranışı deploy gününde doğrulanır.

**Kaydedilecek değerler:** Region, VPC ID, EC2 private IPv4, SSH için public IPv4,
VPC Link ID, iki Cloud Map service ID ve Gateway Invoke URL. Parola ve token bu
listeye girmez.

## 2. EC2'ye kodu taşı ve PostgreSQL'i başlat

Kodu GitHub'a aldıktan sonra EC2'de onaylı repo checkout'unu kullanabilirsin.
Repo hazır değilse Windows'ta proje kökünden yalnızca gereken dosyaları arşivle.
`EC2_PUBLIC_IPV4` ve key pair yolunu kendi değerlerinle değiştir.

```powershell
Set-Location 'C:\Projects\se4458\ai-billing-support-assistant'
$archive = Join-Path ([System.IO.Path]::GetTempPath()) 'se4458-app.tar.gz'
$sshKey = 'C:\PATH\TO\se4458.pem'
$server = 'ubuntu@EC2_PUBLIC_IPV4'
tar.exe -czf $archive --exclude=__pycache__ --exclude='*.pyc' --exclude='.env*' --exclude='*.pem' agent billing_api mcp_server requirements.txt compose.yaml
if ($LASTEXITCODE -ne 0) { throw 'Arşiv oluşturulamadı.' }
tar.exe -tzf $archive
scp.exe -i $sshKey $archive "${server}:~/se4458-app.tar.gz"
ssh.exe -i $sshKey $server
```

EC2 üzerinde Docker Engine ve Compose plugin'i [Docker'ın Ubuntu/arm64
adımlarıyla](https://docs.docker.com/engine/install/ubuntu/) kur.
Aşağıdaki Linux komutları EC2'de çalışır.

```bash
mkdir -p "$HOME/se4458"
tar -xzf "$HOME/se4458-app.tar.gz" -C "$HOME/se4458"
cd "$HOME/se4458"

sudo apt update
sudo apt install -y python3-venv
sudo systemctl enable --now docker
uname -m
sudo docker compose version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -c 'import fastapi, mcp, openai, psycopg, uvicorn'
```

PostgreSQL'i önce kendi başına başlat. Proje kökünde ilk kurulumda Docker
Compose için bir DB parolası üret. Blok mevcut **.env** dosyasını korur.
AWS Compose override, container'ın Docker yeniden başlayınca da
başlatılmasını sağlar. Mevcut Compose named volume veriyi EBS üzerinde
tutar. Init SQL dosyaları boş volume'un ilk açılışında çalışır.

```bash
cd "$HOME/se4458"

if [ ! -e .env ]; then
  (
    umask 077
    pg_secret="$(openssl rand -hex 24)" &&
      printf 'POSTGRES_PASSWORD=%s\n' "$pg_secret" > .env
  )
fi

if [ ! -e compose.aws.yaml ]; then
  cat > compose.aws.yaml <<'YAML'
services:
  postgres:
    restart: unless-stopped
YAML
fi
```

```bash
sudo docker compose -f compose.yaml -f compose.aws.yaml up -d --wait postgres
sudo docker compose -f compose.yaml -f compose.aws.yaml ps postgres
```

```bash
sudo docker compose -f compose.yaml -f compose.aws.yaml exec -T postgres \
  psql -U billing -d billing_dev --set=ON_ERROR_STOP=1 \
  -c "SELECT subscriber_no, bill_year, bill_month, paid_cents FROM bills WHERE subscriber_no='A001' AND bill_year=2026 AND bill_month=10;"
```

Yeni veritabanında **A001 / 2026 / 10 / paid_cents 0** beklenir.
Aynı volume'u yeniden kullandığında init SQL'leri tekrar çalışmaz.

PostgreSQL doğrulandıktan sonra uygulama ayarlarını oluştur.
Aşağıdaki blok DB bağlantı parolasını daha önce oluşturulan **.env**
dosyasından okur. Chat ve Billing için aynı JWT anahtarını üretir.
Demo parolasını ve OpenAI anahtarını gizli terminal girişiyle alır.
Yeniden deploy sırasında mevcut ayar dosyalarını koru.

```bash
(
  set -eu
  umask 077
  mkdir -p "$HOME/.config/se4458"
  for file in "$HOME/.config/se4458/"{billing,chat,mcp}.env; do
    if [ -e "$file" ]; then printf 'Mevcut ayar: %s\n' "$file"; exit 1; fi
  done
  jwt_secret="$(openssl rand -hex 32)"
  read -rsp 'A001 demo password (24+ letters and digits): ' demo_secret
  printf '\n'
  [[ "$demo_secret" =~ ^[a-zA-Z0-9]{24,128}$ ]] || { printf 'A001 password format is invalid.\n' >&2; exit 1; }
  read -rsp 'OpenAI project key: ' openai_secret
  printf '\n'
  [[ "$openai_secret" =~ ^sk-[a-zA-Z0-9_-]+$ ]] || { printf 'OpenAI key format is invalid.\n' >&2; exit 1; }

  db_url="$(.venv/bin/python - <<'PY'
from urllib.parse import quote
from dotenv import dotenv_values

password = dotenv_values(".env").get("POSTGRES_PASSWORD")
if not password:
    raise SystemExit("POSTGRES_PASSWORD is missing from .env")
print(f"postgresql://billing:{quote(password, safe='')}@127.0.0.1:55458/billing_dev")
PY
)"
  printf 'APP_MODULE=billing_api.main:app\nAPP_HOST=0.0.0.0\nAPP_PORT=8000\nBILLING_DATABASE_URL=%s\nBILLING_JWT_SECRET=%s\n' \
    "$db_url" "$jwt_secret" > "$HOME/.config/se4458/billing.env"
  printf 'APP_MODULE=agent.chat_api:app\nAPP_HOST=0.0.0.0\nAPP_PORT=8002\nBILLING_DATABASE_URL=%s\nBILLING_JWT_SECRET=%s\nDEMO_LOGIN_PASSWORD=%s\nOPENAI_API_KEY=%s\nBILLING_API_BASE_URL=https://gateway-pending.invalid\nMCP_URL=http://127.0.0.1:8001/mcp\n' \
    "$db_url" "$jwt_secret" "$demo_secret" "$openai_secret" > "$HOME/.config/se4458/chat.env"
  printf 'APP_MODULE=mcp_server.server:app\nAPP_HOST=127.0.0.1\nAPP_PORT=8001\n' \
    > "$HOME/.config/se4458/mcp.env"
)
```

Operatör akışını canlıda göstereceksen operatörü bu AWS demo DB'de oluştur.
Komut, operator parolasını etkileşimli ister.

```bash
(
  set -a
  . "$HOME/.config/se4458/billing.env"
  set +a
  .venv/bin/python -m agent.operator_accounts operator
)
```

## 3. Üç süreci systemd ile çalıştır

Örnek Ubuntu'nun `ubuntu` kullanıcısını ve `/home/ubuntu/se4458` yolunu
kullanır. Farklı kullanıcı seçersen dosyadaki bu değerleri birlikte değiştir.
Üç servisin ayrı logu var. Chat tek worker çalışır. Restart olursa bekleyen
ödeme ve operatör onayları düşer, kullanıcı yeni taslak açabilir.

```bash
sudo tee /etc/systemd/system/se4458@.service >/dev/null <<'UNIT'
[Unit]
Description=SE4458 %i
Wants=network-online.target
After=network-online.target docker.service

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/se4458
EnvironmentFile=/home/ubuntu/.config/se4458/%i.env
ExecStart=/home/ubuntu/se4458/.venv/bin/python -m uvicorn ${APP_MODULE} --host ${APP_HOST} --port ${APP_PORT} --workers 1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now se4458@billing se4458@mcp se4458@chat
systemctl is-active se4458@billing se4458@mcp se4458@chat
curl -fsS http://127.0.0.1:8000/
curl -fsS http://127.0.0.1:8002/ -o /dev/null
curl -fsS 'http://127.0.0.1:8000/api/v1/subscribers/A001/bills/2026/10'
```

Üç `active`, Billing kökünden JSON ve yeni volume'da faturadan `total: 80.00`
beklenir. Chat başlangıçta Gateway yer tutucusunu kullanır. Bir fatura sorusu
denemeden önce gerçek Invoke URL'yi aşağıdaki adımda gir.

## 4. Gateway ve private integration

1. Cloud Map'te `se4458` adlı **HTTP namespace** oluştur.
   **Instance discovery** alanında **API calls** seç. İki service oluştur
   (`billing` ve `chat`). Her birinde **Register service instance → IP address**
   seçip EC2 private IPv4 ve sırasıyla `8000` / `8002` gir. DNS veya health check
   bu tek instance demo için gerekli değil. **EC2 instance** kayıt türü yerine
   IP address alanı portu da kaydeder. Register işleminin tamamlandığını kontrol et.
2. API Gateway'de `se4458-link` adlı **VPC Link V2** oluştur. EC2 ile aynı
   VPC'nin desteklenen AZ'lerindeki subnet'leri ve `billing-link` SG'yi seç.
   Link `AVAILABLE` olana kadar bekle. VPC Link'in subnet ve SG seçimi sonradan
   değişmez.
3. API Gateway'de **HTTP API** oluştur. `$default` stage ve **Auto-deploy**
   kullan. Bu sayede canlı URL'ye stage prefix eklenmez ve Chat'in
   `/chat-assets` ile `/api/v1` istekleri aynı origin'de çalışır.
4. İki **private resource** integration oluştur. Türü **HTTP proxy**, hedefi
   ilgili Cloud Map service ARN, VPC Link'i `se4458-link`, integration method'u
   `ANY`, payload format version `1.0`. Her integration'da path mapping'i
   `overwrite:path = $request.path` ile ayarla. Console'da **Manage integrations**
   altında hedef integration için **Parameter mapping** alanını kullan.
   Varsayılan HTTP API timeout değeri 30 saniyeyi aşamaz.
5. Aşağıdaki route'ları ilgili integration'a bağla. App'in HS256 token'ı için
   Gateway route authorization `NONE` kalır. Uygulamalar gelen
   `Authorization: Bearer ...` header'ını doğrular. API Gateway'in hazır JWT
   authorizer'ı RSA tabanlı token bekler. Bu projede korumayı FastAPI uygular.
   Tarayıcı ve API aynı URL'yi kullandığından CORS ayarı gerekmiyor.
6. Stage **Logging** ayarına kısa saklama süreli bir CloudWatch log group
   ekleyebilirsin. Access log için örnek format aşağıda. Authorization header,
   body, token veya parola kaydetme. Stage **Throttling** bölümünde demo
   trafiğine uygun bir limit seçebilirsin. Login için örnek başlangıç
   `2 requests/s, burst 5`. Bu yaklaşık ve paylaşılan bir route limitidir.
7. Stage'deki **Invoke URL**'yi kopyala. EC2 üzerindeki
   `~/.config/se4458/chat.env` içinde `BILLING_API_BASE_URL` değerini bu
   HTTPS URL ile değiştir ve `sudo systemctl restart se4458@chat` çalıştır.

```json
{"requestId":"$context.requestId","routeKey":"$context.routeKey","status":"$context.status","integrationStatus":"$context.integration.status","integrationLatency":"$context.integration.latency"}
```

Console Cloud Map hedefini sunmazsa aşağıdaki komutu AWS CloudShell Bash'te
her hedef için bir kez çalıştır. Aynı Region açık olmalı. Değerler API ID,
VPC Link ID ve ilgili Cloud Map **service ARN**'i. Dönen Integration ID'yi
Console'daki route'a bağla.

```bash
read -rp 'HTTP API ID: ' gw_api_id
read -rp 'VPC Link ID: ' gw_link_id
read -rp 'Cloud Map service ARN: ' gw_service_arn
aws apigatewayv2 create-integration --api-id "$gw_api_id" \
  --integration-type HTTP_PROXY --integration-method ANY \
  --connection-type VPC_LINK --connection-id "$gw_link_id" \
  --integration-uri "$gw_service_arn" --payload-format-version 1.0 \
  --request-parameters '{"overwrite:path":"$request.path"}' \
  --timeout-in-millis 30000 --query IntegrationId --output text
```

### Route eşlemeleri

| Method | Gateway path | Integration | Uygulama kontrolü |
| --- | --- | --- | --- |
| GET | `/` | Chat | Login/Chat HTML |
| GET | `/chat-assets/{proxy+}` | Chat | CSS ve JS |
| POST | `/api/v1/auth/login` | Chat | Demo/operatör giriş bilgileri |
| POST | `/api/v1/chat` | Chat | Abone JWT |
| POST | `/api/v1/chat/payments/confirm` | Chat | Abone JWT, açık onay ve taslak sahibi |
| POST | `/api/v1/operator/operations/prepare` | Chat | Operatör JWT ve `billing:write` |
| POST | `/api/v1/operator/operations/confirm` | Chat | Operatör JWT, `billing:write` ve taslak onayı |
| GET | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}` | Billing | Sahip JWT veya public olarak işaretlenmiş sentetik özet |
| GET | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/details` | Billing | Fatura sahibi JWT |
| POST | `/api/v1/subscribers/{subscriber_no}/bills/{year}/{month}/payments` | Billing | Fatura sahibi JWT |
| POST | `/api/v1/usage` | Billing | `billing:write` |
| POST | `/api/v1/bills/calculate` | Billing | `billing:write` |

Billing GET `/` EC2 içi tanılama için kullanılır. Gateway GET `/` Chat UI'ı
açar. MCP `/mcp` ve PostgreSQL yalnız loopback üzerindedir. Proje API sözleşmeleri
[Billing OpenAPI](openapi/billing.openapi.json) ve
[Chat OpenAPI](openapi/chat.openapi.json) dosyalarındadır.

## 5. Canlı kabul ve teslim kanıtları

### İlk iki Gateway route'u ve auth

Tarayıcıda Invoke URL'yi aç. Login ekranı, CSS ve JS yüklenmeli. Windows
PowerShell'de Invoke URL'yi gerçek HTTPS değerine çevirip aşağıdaki bloğu
çalıştır. `curl.exe` status kodunu gösterir ve login token'ı process belleğinde tutulur.

```powershell
$gw = 'https://YOUR_API_ID.execute-api.YOUR_REGION.amazonaws.com'
$billPath = '/api/v1/subscribers/A001/bills/2026/10'
$detailsUrl = "$gw$billPath/details?page=2&pageSize=1"
curl.exe -sS -o NUL -w "summary HTTP %{http_code}\n" "$gw$billPath"
curl.exe -sS -o NUL -w "no JWT HTTP %{http_code}\n" $detailsUrl

$demoSecret = Read-Host 'A001 demo password' -AsSecureString
$credential = [pscredential]::new('A001', $demoSecret)
$loginBody = @{username = 'A001'; password = $credential.GetNetworkCredential().Password} | ConvertTo-Json -Compress
try {
    $session = Invoke-RestMethod -Method Post -Uri "$gw/api/v1/auth/login" -ContentType 'application/json' -Body $loginBody -ErrorAction Stop
    $auth = @{Authorization = "Bearer $($session.token)"}
    $details = Invoke-WebRequest -UseBasicParsing -Uri $detailsUrl -Headers $auth -ErrorAction Stop
    "owner JWT HTTP $($details.StatusCode)"
    $details.Content | ConvertFrom-Json | Select-Object total, remainingBalance, page, pageSize, totalItems
} finally {
    Remove-Variable loginBody, credential, demoSecret, session, auth -ErrorAction SilentlyContinue
}
```

| Kontrol | Beklenen sonuç |
| --- | --- |
| Gateway özet, token yok | `200` ve sentetik A001 toplamı `80.00` |
| Gateway korumalı detay, token yok | `401` |
| Gateway korumalı detay, A001 JWT | `200`, `page=2`, `pageSize=1`, `totalItems=2` |
| Aynı detay, değiştirilmiş token | `401` |
| A001 token ile farklı abonenin detay yolu | `403` |

### Chat ve ödeme

| Kullanıcı sorusu veya eylemi | Kanıt |
| --- | --- |
| `20 GB paketimi 1 GB geçersem ek ücret ne kadar?` | MCP araması `3.2`, `$10` ek ücret |
| `Ekim 2026 faturam kaç dolar?` | Billing REST, kayıtlı `$80` toplam |
| `Ekim 2026 internet ücretim neden $70?` | REST'ten `35 GB`, MCP'den blok kuralı, `$50 + $20` |
| `Ekim 2026 faturama $20 öde.` | Yeni seed varsa onay önce `$80`. Onay butonuna bastıktan sonra `$60`. Chat confirm ve Billing payment istekleri Gateway logunda görünür. |
| Aynı confirmation ID'nin yeniden gönderilmesi | `409` ve bakiye değişmez. |
| MCP'de ek internet, kısmi ödeme, kısıtlama | Üç farklı retrieval için `3.2`, `5.1`, `6.3`. Yeniden üretim adımları [README](../README.md#mcp-billing-guide) ve [kayıtlı yerel kanıt](LOCAL_DEMO_EVIDENCE.md) içinde. |

Üç Chat sorusunda Gateway latency'yi ölç. Birleşik akışta API Gateway HTTP
API'nin maksimum integration timeout'u 30 saniye. Canlı çağrı bu süreyi
aşarsa `504` için Gateway ve Chat loglarını karşılaştır. Ödeme onayı sırasında
`504` alırsan tekrar onay göndermeden önce fatura bakiyesini kontrol et.
Tekrarlayan Chat timeout'ları varsa latency'yi ölçüp alternatif tasarımı
değerlendir. Bu durum canlı kabulü açık bırakır.

```bash
sudo journalctl -u se4458@chat -u se4458@billing -u se4458@mcp -n 80 --no-pager
```

**README teslim kaydı:** Canlı HTTPS Invoke URL, route eşlemeleri, deploy
adımları, A001 test verisi ve test komutu, üç Agent senaryosu, üç MCP sorgusu,
korumalı Gateway route için başarı/hata ve simüle ödeme kanıtı. A001 demo parolasını hocayla dersin izin verdiği özel kanaldan paylaş. Ekran kaydı
öncesinde Authorization header, AWS account ID, OpenAI anahtarı ve parola
görünen alanları kapat. Canlı doğrulama çıktısını yerel kanıttan ayrı kaydet.

## 6. Maliyeti ve kapanışı kontrol et

Oluşturmadan önce seçili Region fiyatını, AWS kredini ve kredi bitişini kontrol
et. EC2 çalışma saati, gp3 EBS, public IPv4, Gateway istekleri, Cloud Map
kayıtları/lookup'ları ve varsa CloudWatch Logs maliyet kalemleri. OpenAI ayrı
faturalanır. AWS Budgets'ta cost budget ve e-posta uyarısı ayarlanabilir.
Uyarı sabit harcama limiti değildir. EC2 Stop, compute ücretini keser ancak
kalan EBS ve tutulan diğer ücretli kaynakları Billing'de ayrıca kontrol et.
Hoca URL'ye erişmeyi bitirene kadar demo kaynaklarının aktif kalacağı süreyi
netleştir. Sonrasında önce gerekli kanıtı ve saklamak istediğin veriyi al.
AWS envanterinde EC2, EBS/snapshot, Gateway/stage, VPC Link, CloudWatch ve
Cloud Map kayıtlarını tek tek gözden geçir. Silme işlemleri canlı ders erişimini etkiler.

### Resmi kaynaklar

- [AWS HTTP API private integrations](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-private.html)
- [VPC Link V2 ve Region/AZ desteği](https://docs.aws.amazon.com/apigateway/latest/developerguide/apigateway-vpc-links-v2.html)
- [Cloud Map namespace](https://docs.aws.amazon.com/cloud-map/latest/dg/creating-namespaces.html) ve [IP/port kaydı](https://docs.aws.amazon.com/cloud-map/latest/dg/registering-instances.html)
- [Gateway parameter mapping](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-parameter-mapping.html), [JWT authorizer](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html), [timeout sınırı](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-quotas.html)
- [EBS ve EC2 stop/start](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/how-ec2-instance-stop-start-works.html) ve [terminate sırasında root volume](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/configure-root-volume-delete-on-termination.html)
- [AWS Pricing Calculator](https://calculator.aws/), [Cloud Map fiyatı](https://aws.amazon.com/cloud-map/pricing/) ve [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
