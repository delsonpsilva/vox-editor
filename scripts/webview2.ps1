# Confere se o Microsoft Edge WebView2 (motor da janela própria) está instalado; se não estiver, instala.
$ErrorActionPreference = "SilentlyContinue"
$id = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
$keys = @("HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$id", "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id",
          "HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$id")
$ok = $false
foreach ($k in $keys) { $pv = (Get-ItemProperty $k).pv; if ($pv -and $pv -ne "0.0.0.0") { $ok = $true } }
if ($ok) { Write-Host "      OK - WebView2 já instalado" -ForegroundColor Green; exit 0 }
Write-Host "      Instalando o Microsoft Edge WebView2..." -ForegroundColor Yellow
if (Get-Command winget) {
    winget install -e --id Microsoft.EdgeWebView2Runtime --accept-package-agreements --accept-source-agreements --silent | Out-Null
} else {
    $exe = Join-Path $env:TEMP "webview2-setup.exe"
    Invoke-WebRequest "https://go.microsoft.com/fwlink/p/?LinkId=2124703" -OutFile $exe
    Start-Process $exe -ArgumentList "/silent /install" -Wait
}
Write-Host "      OK - WebView2 pronto (se a janela própria não abrir, use o INICIAR-NAVEGADOR.bat)" -ForegroundColor Green
