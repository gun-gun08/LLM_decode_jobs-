# Setup of the LOCAL Odoo 19 instance from this package: PostgreSQL + Odoo in Docker, the Recruitment website and the llmd_job_aggregator addon.
# Services: Odoo + PostgreSQL only. Images: odoo:19.0 (~700 MB download) and postgres:16-alpine. Needs ~3 GB free disk.
#   .\scripts\setup.ps1            new instance: creates .env, the database, installs the addon, seeds the company (10-15 minutes the first time)
#                                  existing database (same COMPOSE_PROJECT_NAME / ODOO_DB): only starts it and updates the addon - nothing is seeded again
#   .\scripts\setup.ps1 -Reset     delete THIS project's local database + filestore volumes and start again (local only, asks to confirm)
param([switch]$Reset)
$ErrorActionPreference = 'Continue'      # docker writes progress to stderr; success is judged by the exit codes below
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
. (Join-Path $PSScriptRoot 'env.ps1') -Create
$composeArgs = @('--env-file', (Join-Path $root '.env'), '-f', (Join-Path $root 'docker\docker-compose.yml'))
function Compose { docker compose @composeArgs @args }

# --- checks that explain the errors instead of failing half-way ---------------------------------------------------------------
docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not running. Start Docker Desktop and try again.' }
$freeGb = [math]::Round((Get-PSDrive -Name ((Get-Location).Drive.Name)).Free / 1GB, 1)
$haveOdoo = $false; docker image inspect odoo:19.0 *> $null; if ($LASTEXITCODE -eq 0) { $haveOdoo = $true }
if (-not $haveOdoo -and $freeGb -lt 3) { throw "Only $freeGb GB free on this drive; the Odoo image needs ~3 GB. Free some space first." }

if ($Reset) {
    $project = if ($env:COMPOSE_PROJECT_NAME) { $env:COMPOSE_PROJECT_NAME } else { 'llmd-local' }
    if ((Read-Host "Type '$project' to DELETE the database and filestore volumes of project $project") -ne $project) { throw 'not confirmed - nothing deleted' }
    Compose down -v; if ($LASTEXITCODE -ne 0) { throw 'could not remove the old local containers' }
}

# --- images (only what is missing) ---------------------------------------------------------------------------------------------
if (-not $haveOdoo) { docker pull odoo:19.0; if ($LASTEXITCODE -ne 0) { throw 'download of odoo:19.0 failed' } }
docker image inspect postgres:16-alpine *> $null; if ($LASTEXITCODE -ne 0) { docker pull postgres:16-alpine; if ($LASTEXITCODE -ne 0) { throw 'download of postgres:16-alpine failed' } }

# --- database ------------------------------------------------------------------------------------------------------------------
Compose up -d --wait db
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL did not start (wrong POSTGRES_PASSWORD for an existing volume? use the .env that created it)' }
$exists = (Compose exec -T db psql -U $env:POSTGRES_USER -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$($env:ODOO_DB)'") -eq '1'

if ($exists) {
    Write-Host "`nDatabase '$($env:ODOO_DB)' already exists: updating the llmd_job_aggregator addon only (no new data)..."
    Compose run --rm odoo odoo -d $env:ODOO_DB --db-filter="^$($env:ODOO_DB)$" -u llmd_job_aggregator --stop-after-init
    if ($LASTEXITCODE -ne 0) { throw 'addon update failed - read the log above' }
} else {
    Write-Host "`nInitialising database '$($env:ODOO_DB)' with the Recruitment website + llmd_job_aggregator, no demo data - several minutes..."
    Compose run --rm odoo odoo -d $env:ODOO_DB --db-filter="^$($env:ODOO_DB)$" -i 'website_hr_recruitment,llmd_job_aggregator' --without-demo=all --stop-after-init      # quoted: unquoted, PowerShell would pass two words
    if ($LASTEXITCODE -ne 0) { throw 'database initialisation failed - read the log above (a "read-only file system" error means the disk is full)' }
}

Compose up -d odoo
Write-Host 'waiting for Odoo to answer...'
$up = $false
for ($i = 0; $i -lt 60; $i++) {
    try { if ((Invoke-WebRequest -UseBasicParsing "$($env:ODOO_URL)/web/login" -TimeoutSec 5).StatusCode -eq 200) { $up = $true; break } } catch { Start-Sleep -Seconds 3 }
}
if (-not $up) { throw "Odoo did not answer on $($env:ODOO_URL) - run: docker compose --env-file .env -f docker\docker-compose.yml logs odoo" }

if (-not $exists) {
    python (Join-Path $PSScriptRoot 'seed_local.py')
    if ($LASTEXITCODE -ne 0) { throw 'seeding the local company and jobs failed' }
}
Write-Host "`nLocal instance is ready:  $($env:ODOO_URL)/jobs   (Odoo backend: $($env:ODOO_URL)/odoo, database $($env:ODOO_DB), user $($env:ODOO_USER), password in .env)"
Write-Host 'Next: fetch real jobs with   python tests\board_test.py fetch   and run the checks (README, "Testing").'
