# After a change of the code: installs the llmd_job_aggregator addon from this folder into the LOCAL database (views, fields, migrations) and restarts
# Odoo, so that the website shows the change (the stylesheet and script bundle is built again too). Nothing else of the database is touched.
#   .\scripts\update_local.ps1
$ErrorActionPreference = 'Continue'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
. (Join-Path $PSScriptRoot 'env.ps1')
$composeArgs = @('--env-file', (Join-Path $root '.env'), '-f', (Join-Path $root 'docker\docker-compose.yml'))
function Compose { docker compose @composeArgs @args }

docker info *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker engine is not running: run .\scripts\start_local.ps1 first.' }
Compose stop odoo                                               # a running job sync would hold locks the update needs
Compose run --rm odoo odoo -d $env:ODOO_DB --db-filter="^$($env:ODOO_DB)$" -u llmd_job_aggregator --stop-after-init
$failed = $LASTEXITCODE -ne 0
Compose start odoo
if ($failed) { throw 'the addon update failed - read the log above (Odoo is running again with the previous version)' }
Write-Host "Addon updated, Odoo restarted: http://127.0.0.1:$($env:ODOO_PORT)/jobs"
