# Restores a backup made by backup_local.ps1 into a database of this LOCAL instance (database + filestore).
#   .\scripts\restore_local.ps1 -From backups\llmd_local_20261024-120000
#        into a NEW database "<ODOO_DB>_restored" - the current database is not touched (to open it: ODOO_DB=<that name> in .env, then restart Odoo)
#   .\scripts\restore_local.ps1 -From backups\llmd_local_20261024-120000 -Database llmd_local -Replace
#        REPLACES that database (asks you to type its name; Odoo is stopped while the database is swapped)
param([Parameter(Mandatory = $true)][string]$From, [string]$Database = '', [switch]$Replace)
$ErrorActionPreference = 'Continue'      # docker writes progress to stderr; success is judged by the exit codes below
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'env.ps1')
$composeArgs = @('--env-file', (Join-Path $root '.env'), '-f', (Join-Path $root 'docker\docker-compose.yml'))
function Compose { docker compose @composeArgs @args; if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed" } }

$dump = Join-Path $From 'database.dump'
if (-not (Test-Path $dump)) { throw "$dump not found" }
if (-not $Database) { $Database = "$($env:ODOO_DB)_restored" }
if ($Database -notmatch '^[A-Za-z0-9_-]+$') { throw 'database name: letters, digits, _ and - only' }
$user = $env:POSTGRES_USER
$exists = (docker compose @composeArgs exec -T db psql -U $user -d postgres -Atc "SELECT 1 FROM pg_database WHERE datname = '$Database'") -eq '1'

if ($exists -and -not $Replace) { throw "database $Database already exists - pick another -Database, or add -Replace to overwrite it" }
if ($Replace) {
    if ((Read-Host "Type '$Database' to REPLACE that database with the backup") -ne $Database) { throw 'not confirmed - nothing changed' }
    Compose stop odoo
    if ($exists) { Compose exec -T db dropdb -U $user $Database }
}

Write-Host "database <- $dump  (into $Database)"
Compose exec -T db createdb -U $user -O $user $Database
Compose cp $dump db:/tmp/llmd_restore.dump
Compose exec -T db pg_restore -U $user -d $Database --no-owner --role=$user /tmp/llmd_restore.dump
Compose exec -T db rm -f /tmp/llmd_restore.dump

if ($Replace) { Compose start odoo }
$files = Join-Path $From 'filestore'
if (Test-Path $files) {
    Write-Host "filestore <- $files"
    Compose exec -T odoo rm -rf "/var/lib/odoo/filestore/$Database"
    Compose exec -T odoo mkdir -p /var/lib/odoo/filestore
    Compose cp $files "odoo:/var/lib/odoo/filestore/$Database"
    Compose exec -T -u root odoo chown -R odoo:odoo "/var/lib/odoo/filestore/$Database"
}
if ($Replace) { Compose restart odoo }
Write-Host "`nRestore done: database $Database"
