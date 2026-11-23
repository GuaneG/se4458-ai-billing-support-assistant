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
$publicChecks = @(
    @{ Label = 'Summary'; Url = $summaryUrl; Expected = '200' }
    @{ Label = 'Detail without JWT'; Url = $detailUrl; Expected = '401' }
)

foreach ($check in $publicChecks) {
    $status = curl.exe -sS -o NUL -w '%{http_code}' --connect-timeout 8 --max-time 20 $check.Url
    if ($LASTEXITCODE -ne 0) {
        throw "$($check.Label) istegi Gateway'e ulasamadi."
    }
    "$($check.Label) HTTP $status"
    if ($status -ne $check.Expected) {
        throw "$($check.Label) icin beklenen HTTP durumu $($check.Expected)."
    }
}

try {
    $demoPassword = Read-Host 'A001 demo parolasi' -AsSecureString
    $demoCredential = [pscredential]::new('A001', $demoPassword)
    $loginBody = @{
        username = 'A001'
        password = $demoCredential.GetNetworkCredential().Password
    } | ConvertTo-Json -Compress
    $session = Invoke-RestMethod -Method Post -Uri "$gatewayBase/api/v1/auth/login" `
        -ContentType 'application/json' -Body $loginBody -TimeoutSec 20
    $headers = @{ Authorization = "Bearer $($session.token)" }
    $detail = Invoke-WebRequest -UseBasicParsing -Uri $detailUrl `
        -Headers $headers -TimeoutSec 20
    "Detail with owner JWT HTTP $($detail.StatusCode)"

    $bill = $detail.Content | ConvertFrom-Json
    $returnedItems = @($bill.chargeBreakdown).Count
    if ($detail.StatusCode -ne 200 -or $bill.page -ne 2 -or $bill.pageSize -ne 1 -or $returnedItems -ne 1) {
        throw 'Beklenen 200 yaniti ve bir kalemlik ikinci sayfa dogrulanamadi.'
    }
    $bill | Select-Object total, paidAmount, remainingBalance, page, pageSize, totalItems,
        @{ Name = 'returnedItems'; Expression = { $returnedItems } }
} finally {
    Remove-Variable demoPassword, demoCredential, loginBody, session, headers -ErrorAction SilentlyContinue
}
