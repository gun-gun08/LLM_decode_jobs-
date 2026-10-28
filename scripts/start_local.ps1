# Starts the LOCAL site in one go: Docker Desktop (when it is not running yet), PostgreSQL + Odoo, then opens the Jobs Explorer in the browser.
# Nothing is installed or changed: the existing local database is used as it is (first time ever on this computer: .\scripts\setup.ps1).
#   .\scripts\start_local.ps1            start + open http://127.0.0.1:<ODOO_PORT>/jobs
#   .\scripts\start_local.ps1 -NoBrowser start only
# VS Code runs it by itself when the folder is opened (task "Start local site", .vscode\tasks.json).
param([switch]$NoBrowser)
$ErrorActionPreference = 'Continue'      # docker writes progress to stderr; success is judged by the exit codes below
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
. (Join-Path $PSScriptRoot 'env.ps1')
$composeArgs = @('--env-file', (Join-Path $root '.env'), '-f', (Join-Path $root 'docker\docker-compose.yml'))
function Compose { docker compose @composeArgs @args }

# --- 1. Docker Desktop -----------------------------------------------------------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    $exe = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
    if (-not (Test-Path $exe)) { throw "Docker Desktop is not installed ($exe). Install it from https://www.docker.com/products/docker-desktop/ first." }
    Write-Host 'Starting Docker Desktop...'
    Start-Process $exe
    $deadline = (Get-Date).AddMinutes(4)
    do {
        Start-Sleep -Seconds 5
        docker info *> $null
    } while ($LASTEXITCODE -ne 0 -and (Get-Date) -lt $deadline)
    if ($LASTEXITCODE -ne 0) { throw 'Docker Desktop did not start within 4 minutes. Open it by hand, wait for "Engine running", then run this again.' }
}
Write-Host 'Docker engine: running'

# --- 2. PostgreSQL + Odoo --------------------------------------------------------------------------------------------------------
Compose up -d
if ($LASTEXITCODE -ne 0) { throw 'the local containers did not start - read the log above (no local database yet? run .\scripts\setup.ps1 once)' }

# --- 3. wait for the website ------------------------------------------------------------------------------------------------------
$url = "http://127.0.0.1:$($env:ODOO_PORT)/jobs"
Write-Host "Waiting for $url ..."
$deadline = (Get-Date).AddMinutes(3)
$ready = $false
while (-not $ready -and (Get-Date) -lt $deadline) {
    try { $ready = (Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10).StatusCode -eq 200 } catch { Start-Sleep -Seconds 3 }
}
if (-not $ready) { throw "Odoo did not answer on $url within 3 minutes. See the log: docker compose --env-file .env -f docker\docker-compose.yml logs --tail 80 odoo" }

Write-Host ''
Write-Host "Ready:  website (Jobs Explorer)  $url"
Write-Host "        Odoo backend             http://127.0.0.1:$($env:ODOO_PORT)/odoo   (login: ODOO_USER / ODOO_PASSWORD of .env)"
if (-not $NoBrowser) { Start-Process $url }
