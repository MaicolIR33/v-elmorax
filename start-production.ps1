$envFile = Join-Path $PSScriptRoot ".env.production"
$envExampleFile = Join-Path $PSScriptRoot ".env.production.example"

if (-not (Test-Path $envFile)) {
    if (Test-Path $envExampleFile) {
        Copy-Item $envExampleFile $envFile
        Write-Host ""
        Write-Host "No existia .env.production. Se creo una copia base desde .env.production.example." -ForegroundColor Yellow
        Write-Host "Revisa ese archivo antes de usar Velmorax en produccion real." -ForegroundColor Yellow
        Write-Host ""
    }
    else {
        Write-Error "No se encontro .env.production en $PSScriptRoot"
        exit 1
    }
}

Get-Content $envFile | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) {
        return
    }

    $parts = $line -split "=", 2
    if ($parts.Length -ne 2) {
        return
    }

    $name = $parts[0].Trim()
    $value = $parts[1].Trim()
    [System.Environment]::SetEnvironmentVariable($name, $value, "Process")
}

if (-not (Test-Path ".\.venv\Scripts\python.exe")) {
    Write-Error "No se encontro el interprete en .venv\Scripts\python.exe"
    exit 1
}

$appPort = [System.Environment]::GetEnvironmentVariable("APP_PORT", "Process")
if (-not $appPort) {
    $appPort = [System.Environment]::GetEnvironmentVariable("PORT", "Process")
}
if (-not $appPort) {
    $appPort = "8000"
}

$appUrl = "http://127.0.0.1:$appPort/login"

function Test-VelmoraxEndpoint {
    param(
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
        if ($response.StatusCode -eq 200 -and $response.Content -match "Velmorax") {
            return $true
        }
    }
    catch {
        return $false
    }

    return $false
}

$portInUse = Get-NetTCPConnection -LocalPort $appPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" } |
    Select-Object -First 1

if ($portInUse) {
    $ownerProcess = Get-Process -Id $portInUse.OwningProcess -ErrorAction SilentlyContinue
    $ownerName = if ($ownerProcess) { $ownerProcess.ProcessName } else { "desconocido" }

    if (Test-VelmoraxEndpoint -Url $appUrl) {
        Write-Host ""
        Write-Host "Velmorax ya esta corriendo en el puerto $appPort." -ForegroundColor Green
        Write-Host "Abriendo: $appUrl" -ForegroundColor Green
        Write-Host ""
        Start-Process $appUrl
        exit 0
    }

    Write-Host ""
    Write-Host "El puerto $appPort ya esta en uso por el proceso $ownerName (PID $($portInUse.OwningProcess))." -ForegroundColor Yellow
    Write-Host "No parece ser una instancia accesible de Velmorax en $appUrl." -ForegroundColor Yellow
    Write-Host "Si quieres otro puerto para esta ejecucion, usa por ejemplo: `$env:APP_PORT='8001'; .\start-production.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 0
}

$databaseUrl = [System.Environment]::GetEnvironmentVariable("DATABASE_URL", "Process")
$databaseFallbackUrl = [System.Environment]::GetEnvironmentVariable("DATABASE_FALLBACK_URL", "Process")
$allowLocalSqliteFallback = [System.Environment]::GetEnvironmentVariable("ALLOW_LOCAL_SQLITE_FALLBACK", "Process")

if (-not $databaseFallbackUrl) {
    $databaseFallbackUrl = "sqlite:///data/velmorax.db"
}

if (-not $allowLocalSqliteFallback) {
    $allowLocalSqliteFallback = "1"
}

if ($databaseUrl -and ($databaseUrl.StartsWith("postgres://") -or $databaseUrl.StartsWith("postgresql://"))) {
    $preflight = @'
import os
import sys
from urllib.parse import urlparse

import psycopg

database_url = os.environ.get("DATABASE_URL", "")

try:
    connection = psycopg.connect(database_url, connect_timeout=5)
    connection.close()
except Exception as exc:
    parsed = urlparse(database_url)
    user = parsed.username or "sin_usuario"
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    database = (parsed.path or "/").lstrip("/") or "sin_base"

    print("")
    print("No se pudo validar la conexion PostgreSQL antes de iniciar Velmorax.")
    print(f"Servidor: {host}:{port}")
    print(f"Base: {database}")
    print(f"Usuario: {user}")
    print("")
    print("Que debes revisar:")
    print("1. La clave del DATABASE_URL dentro de .env.production.")
    print("2. Si tu PostgreSQL local usa otro usuario, cambia DATABASE_URL a ese usuario real.")
    print("3. Si quieres usar la configuracion del proyecto, crea el usuario/clave esperados en PostgreSQL.")
    print("")
    detail = str(exc).encode("ascii", "replace").decode("ascii")
    print(f"Detalle tecnico: {detail}")

    allow_fallback = os.environ.get("ALLOW_LOCAL_SQLITE_FALLBACK", "1") in {"1", "true", "True"}
    is_local_host = host in {"localhost", "127.0.0.1", "::1"}
    fallback_url = os.environ.get("DATABASE_FALLBACK_URL", "sqlite:///data/velmorax.db")

    if allow_fallback and is_local_host:
        print("")
        print("Se activara el respaldo local con SQLite para que Velmorax pueda iniciar en este equipo.")
        print(f"Base de respaldo: {fallback_url}")
        sys.exit(3)

    sys.exit(2)
'@

    $preflight | .\.venv\Scripts\python.exe -
    if ($LASTEXITCODE -eq 3) {
        [System.Environment]::SetEnvironmentVariable("DATABASE_URL", $databaseFallbackUrl, "Process")
        Write-Host ""
        Write-Host "Velmorax seguira con base SQLite local para este arranque." -ForegroundColor Yellow
        Write-Host "DATABASE_URL activo: $databaseFallbackUrl" -ForegroundColor Yellow
        Write-Host ""
    }
    elseif ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

Start-Process -FilePath powershell -ArgumentList @(
    "-NoProfile",
    "-WindowStyle",
    "Hidden",
    "-Command",
    "Start-Sleep -Seconds 3; Start-Process '$appUrl'"
) | Out-Null

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port $appPort
