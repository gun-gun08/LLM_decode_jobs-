# Stops the LOCAL site (Odoo + PostgreSQL). The database stays as it is; .\scripts\start_local.ps1 starts it again.
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
. (Join-Path $PSScriptRoot 'env.ps1')
docker compose --env-file (Join-Path $root '.env') -f (Join-Path $root 'docker\docker-compose.yml') stop
if ($LASTEXITCODE -ne 0) { throw 'could not stop the local containers (is Docker Desktop running?)' }
Write-Host 'Local site stopped (the data is kept).'
