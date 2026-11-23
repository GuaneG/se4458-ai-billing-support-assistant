[CmdletBinding()]
param(
    [uri] $GatewayUrl = 'https://suj7bul3re.execute-api.eu-north-1.amazonaws.com'
)

$ErrorActionPreference = 'Stop'
if (-not $GatewayUrl.IsAbsoluteUri -or $GatewayUrl.Scheme -ne 'https') {
    throw 'GatewayUrl HTTPS olmalidir.'
}

$gatewayBase = $GatewayUrl.AbsoluteUri.TrimEnd('/')
$summaryUrl = "$gatewayBase/api/v1/subscribers/A001/bills/2026/10"
$detailUrl = "$summaryUrl/details?page=2&pageSize=1"

# 1. Read the public demo summary.
'1. Fatura ozeti (JWT yok)'
$summary = Invoke-WebRequest -UseBasicParsing -Uri $summaryUrl -TimeoutSec 20
if ($summary.StatusCode -ne 200) {
    throw 'Fatura ozeti icin HTTP 200 bekleniyor.'
}
"HTTP $($summary.StatusCode)"
$summary.Content | ConvertFrom-Json | ConvertTo-Json -Depth 4

# 2. Check that the detail requires a JWT.
''
'2. Fatura detayi (JWT yok)'
$anonymousStatus = curl.exe -sS -o NUL -w '%{http_code}' --connect-timeout 8 --max-time 20 $detailUrl
if ($LASTEXITCODE -ne 0 -or $anonymousStatus -ne '401') {
    throw "JWT'siz detay icin HTTP 401 bekleniyor. Alinan durum: $anonymousStatus"
}
"HTTP $anonymousStatus"

# 3. Sign in, then read one charge from the second page.
''
'3. Fatura detayi (A001 JWT ile)'
try {
    $demoPassword = Read-Host 'A001 demo parolasi' -AsSecureString
    $demoCredential = [pscredential]::new('A001', $demoPassword)
    $loginBody = @{
        username = 'A001'
        password = $demoCredential.GetNetworkCredential().Password
    } | ConvertTo-Json -Compress
    $loginRequest = @{
        Method = 'Post'
        Uri = "$gatewayBase/api/v1/auth/login"
        ContentType = 'application/json'
        Body = $loginBody
        TimeoutSec = 20
    }
    $session = Invoke-RestMethod @loginRequest  #Login isteği atıldı ve session var'da saklanıldı.
    $headers = @{ Authorization = "Bearer $($session.token)" } #JWT header'a eklenildi
    $detail = Invoke-WebRequest -UseBasicParsing -Uri $detailUrl -Headers $headers -TimeoutSec 20 #JWT ile istek beklenen 200

    $bill = $detail.Content | ConvertFrom-Json
    $returnedItems = @($bill.chargeBreakdown).Count
    if ($detail.StatusCode -ne 200 -or $bill.page -ne 2 -or $bill.pageSize -ne 1 -or $returnedItems -ne 1) {
        throw 'Beklenen 200 yaniti ve bir kalemlik ikinci sayfa dogrulanamadi.'
    }
    "HTTP $($detail.StatusCode)"
    $bill | Select-Object total, paidAmount, remainingBalance, phoneMinutes, internetGb,
        page, pageSize, totalItems, chargeBreakdown | ConvertTo-Json -Depth 4
    "returnedItems = $returnedItems"
} finally {
    Remove-Variable demoPassword, demoCredential, loginBody, loginRequest, session, headers -ErrorAction SilentlyContinue
}
