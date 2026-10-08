param(
    [string]$HostAddress = $env:OLLAMA_HOST
)

if ([string]::IsNullOrWhiteSpace($HostAddress)) {
    $HostAddress = "127.0.0.1:12000"
}

$env:OLLAMA_HOST = $HostAddress
$apiBase = if ($HostAddress -match '^https?://') {
    $HostAddress.TrimEnd('/')
} else {
    "http://$HostAddress"
}

function Test-Ollama {
    try {
        $null = Invoke-RestMethod -Uri "$apiBase/api/tags" -TimeoutSec 2
        return $true
    } catch {
        return $false
    }
}

Write-Host "Checking local Ollama at $apiBase ..."

if (Test-Ollama) {
    Write-Host "  Ollama: AVAILABLE" -ForegroundColor Green
    exit 0
}

$cmd = Get-Command ollama.exe -ErrorAction SilentlyContinue
if (-not $cmd) {
    Write-Host "  Ollama executable was not found in PATH." -ForegroundColor Red
    exit 1
}

Write-Host "  Ollama is not running. Starting it..." -ForegroundColor Yellow
Start-Process -FilePath $cmd.Source -ArgumentList "serve" -WindowStyle Hidden

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Milliseconds 500
    if (Test-Ollama) {
        Write-Host "  Ollama: STARTED at $apiBase" -ForegroundColor Green
        exit 0
    }
}

Write-Host "  Ollama did not become ready at $apiBase." -ForegroundColor Red
exit 1
