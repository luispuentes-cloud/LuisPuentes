# Export the root CA that your network's TLS inspection presents for Cursor,
# into a PEM bundle Node can trust via NODE_EXTRA_CA_CERTS.
#
#   powershell -ExecutionPolicy Bypass -File tools\export_corp_ca.ps1
#
# Writes: %USERPROFILE%\.cursor\corp-ca.pem
# Reads only the local certificate store. Sends no data anywhere.

$ErrorActionPreference = 'Stop'

$targetHost = 'api.cursor.com'
$targetPort = 443
$outFile = Join-Path $env:USERPROFILE '.cursor\corp-ca.pem'

New-Item -ItemType Directory -Force -Path (Split-Path $outFile) | Out-Null

Write-Host "Connecting to ${targetHost}:${targetPort} to capture the presented chain..."

$client = New-Object System.Net.Sockets.TcpClient
$client.Connect($targetHost, $targetPort)
$stream = $client.GetStream()

# Accept any certificate: the point is to inspect what interception presents,
# not to validate it.
$ssl = New-Object System.Net.Security.SslStream($stream, $false, { $true })
$leaf = $null
try {
    $ssl.AuthenticateAsClient($targetHost)
    $remote = $ssl.RemoteCertificate
    if ($remote) {
        $leaf = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2 $remote
    }
} finally {
    $ssl.Dispose()
    $client.Close()
}

if (-not $leaf) {
    Write-Host 'FAIL: no server certificate captured.'
    exit 1
}

$chain = New-Object System.Security.Cryptography.X509Certificates.X509Chain
$chain.ChainPolicy.RevocationMode = 'NoCheck'
$chain.ChainPolicy.VerificationFlags = 'AllFlags'
[void]$chain.Build($leaf)

if ($chain.ChainElements.Count -eq 0) {
    Write-Host 'FAIL: could not build a chain from the presented certificate.'
    exit 1
}

$captured = $chain

Write-Host ''
Write-Host 'Presented chain (leaf -> root):'
$i = 0
foreach ($el in $captured.ChainElements) {
    Write-Host ("  [{0}] {1}" -f $i, $el.Certificate.Subject)
    $i++
}

$root = $captured.ChainElements[$captured.ChainElements.Count - 1].Certificate
Write-Host ''
Write-Host "Root of presented chain:"
Write-Host "  Subject : $($root.Subject)"
Write-Host "  Issuer  : $($root.Issuer)"
Write-Host "  Thumb   : $($root.Thumbprint)"

$isPublicCursorRoot = $root.Subject -match 'DigiCert|Amazon|Baltimore|ISRG|Google Trust|GlobalSign'
if ($isPublicCursorRoot) {
    Write-Host ''
    Write-Host 'NOTE: root looks like a public CA, so interception may be selective.'
    Write-Host '      Exporting all non-Microsoft roots as a fallback bundle.'
}

# Export the presented root plus every intermediate, and (when the presented
# root looks public) any additional locally-installed roots that are likely
# inspection CAs. Node accepts a multi-certificate PEM bundle.
$toExport = New-Object System.Collections.Generic.List[System.Security.Cryptography.X509Certificates.X509Certificate2]
foreach ($el in $captured.ChainElements) {
    if ($el.Certificate.Subject -ne $captured.ChainElements[0].Certificate.Subject) {
        $toExport.Add($el.Certificate)
    }
}
$toExport.Add($root)

$inspectionPattern = 'PwC|Pricewaterhouse|pwcglb|pwcglobal|Zscaler|Netskope|Palo Alto|Blue Coat|Broadcom|Forcepoint|McAfee|Umbrella|Fortinet|FortiGate|Sophos|Trend Micro|Check ?Point|Inspection'
foreach ($storeName in @('Root', 'CA')) {
    foreach ($scope in @('LocalMachine', 'CurrentUser')) {
        $path = "Cert:\$scope\$storeName"
        if (-not (Test-Path $path)) { continue }
        Get-ChildItem $path | Where-Object { $_.Subject -match $inspectionPattern } | ForEach-Object {
            $toExport.Add($_)
        }
    }
}

$unique = @{}
$lines = New-Object System.Collections.Generic.List[string]
foreach ($cert in $toExport) {
    if (-not $cert -or $unique.ContainsKey($cert.Thumbprint)) { continue }
    $unique[$cert.Thumbprint] = $true
    $b64 = [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
    $lines.Add("# $($cert.Subject)")
    $lines.Add('-----BEGIN CERTIFICATE-----')
    $lines.Add($b64)
    $lines.Add('-----END CERTIFICATE-----')
    $lines.Add('')
}

Set-Content -Path $outFile -Value ($lines -join "`r`n") -Encoding ascii

Write-Host ''
Write-Host "Wrote $($unique.Count) certificate(s) to:"
Write-Host "  $outFile"
Write-Host ''
Write-Host 'Now test Node against it:'
Write-Host "  `$env:NODE_EXTRA_CA_CERTS = `"$outFile`""
Write-Host '  node tools\node_tls_check.js'
