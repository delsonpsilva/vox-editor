# Instalador do Editor IA para Windows 10/11 (64 bits)
# Faz tudo sozinho: Python, bibliotecas, FFmpeg com suporte a GPU, modelo de transcrição e atalho na área de trabalho.
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Passo($n, $txt) { Write-Host ""; Write-Host "[$n/6] $txt" -ForegroundColor Cyan }
function Ok($txt) { Write-Host "      OK - $txt" -ForegroundColor Green }
function Aviso($txt) { Write-Host "      ! $txt" -ForegroundColor Yellow }

Write-Host ""
Write-Host "  =============================================" -ForegroundColor DarkYellow
Write-Host "        Instalando o Editor IA no seu PC" -ForegroundColor DarkYellow
Write-Host "  =============================================" -ForegroundColor DarkYellow

# ---------- 1. Python ----------
Passo 1 "Procurando o Python (3.10 a 3.13)..."
function Achar-Python {
    foreach ($cand in @(@("py", "-3.12"), @("py", "-3.13"), @("py", "-3.11"), @("py", "-3.10"), @("python"))) {
        try {
            $exe = $cand[0]; $args2 = @(); if ($cand.Count -gt 1) { $args2 = @($cand[1]) }
            $v = & $exe @args2 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v -match '^3\.(1[0-3])$') { return ,$cand }
        } catch {}
    }
    return $null
}
$py = Achar-Python
if (-not $py) {
    Aviso "Python não encontrado. Instalando o Python 3.12 pelo winget..."
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "      Não achei o winget. Instale o Python 3.12 em https://www.python.org/downloads/ (marque 'Add to PATH') e rode o instalador de novo." -ForegroundColor Red
        exit 1
    }
    winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "User") + ";" + [Environment]::GetEnvironmentVariable("Path", "Machine")
    $py = Achar-Python
    if (-not $py) { Write-Host "      Instalei o Python, mas preciso que você feche esta janela e rode o INSTALAR.bat de novo." -ForegroundColor Red; exit 1 }
}
Ok ("Python encontrado: " + ($py -join " "))

# ---------- 2. Ambiente e bibliotecas ----------
Passo 2 "Criando o ambiente e instalando as bibliotecas (alguns minutos)..."
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    $exe = $py[0]; $args2 = @(); if ($py.Count -gt 1) { $args2 = @($py[1]) }
    & $exe @args2 -m venv .venv
}
$vpy = Join-Path $Root ".venv\Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r requirements.txt --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "      Falha ao instalar as bibliotecas. Verifique a internet e rode de novo." -ForegroundColor Red; exit 1 }
Ok "Bibliotecas instaladas"

# ---------- 3. GPU NVIDIA (opcional) ----------
Passo 3 "Verificando placa de vídeo NVIDIA..."
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    $gpu = (& nvidia-smi --query-gpu=name --format=csv,noheader 2>$null | Select-Object -First 1)
    Ok "GPU encontrada: $gpu - instalando aceleração da transcrição (pode demorar)"
    & $vpy -m pip install nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*" --quiet
    if ($LASTEXITCODE -ne 0) { Aviso "Não consegui instalar a aceleração; a transcrição vai usar o processador." }
} else {
    Aviso "Sem GPU NVIDIA: a transcrição usa o processador (funciona, só que mais devagar)."
}

# ---------- 4. FFmpeg ----------
Passo 4 "Baixando o FFmpeg (motor de vídeo, com suporte a NVIDIA/Intel/AMD)..."
if (-not (Test-Path "ffmpeg\bin\ffmpeg.exe")) {
    $zip = Join-Path $env:TEMP "ffmpeg-editor-ia.zip"
    $tmp = Join-Path $env:TEMP "ffmpeg-editor-ia"
    Invoke-WebRequest "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip" -OutFile $zip
    if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
    Expand-Archive $zip -DestinationPath $tmp -Force
    $bin = Get-ChildItem $tmp -Recurse -Filter ffmpeg.exe | Select-Object -First 1
    New-Item -ItemType Directory -Force -Path "ffmpeg\bin" | Out-Null
    Copy-Item (Join-Path $bin.DirectoryName "*.exe") "ffmpeg\bin\" -Force
    Remove-Item $zip, $tmp -Recurse -Force
}
Ok "FFmpeg pronto"

# ---------- 5. Modelo de transcrição ----------
Passo 5 "Baixando o modelo de transcrição (só desta vez, ~500 MB)..."
$env:PYTHONIOENCODING = "utf-8"
& $vpy -c "from faster_whisper import download_model; download_model('small', cache_dir='dados/modelos'); print('modelo ok')"
if ($LASTEXITCODE -ne 0) { Aviso "Não consegui baixar agora; ele será baixado no primeiro vídeo." } else { Ok "Modelo pronto" }

# ---------- 6. Janela própria e atalho ----------
Passo 6 "Preparando a janela própria do programa e o atalho..."
& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "webview2.ps1")
& $vpy -m backend.desktop --atalho

Write-Host ""
Write-Host "  Instalação concluída! Abra pelo atalho na área de trabalho." -ForegroundColor Green
Write-Host "  O programa abre na janela própria dele. Para desligar, é só fechar a janela." -ForegroundColor Green
Write-Host ""
