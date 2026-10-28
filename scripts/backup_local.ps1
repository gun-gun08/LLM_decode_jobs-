# Backs up the LOCAL Odoo database and its filestore into  backups\<db>_<date-time>\  (database.dump = pg_dump custom format, filestore\ = attachments).
# A backup holds EVERYTHING in the database - applicant names, e-mails, phones, resumes, click lines: keep it private, never commit, upload or share it.
#   .\scripts\backup_local.ps1                    (from the package root, with the instance running)
#   .\scripts\backup_local.ps1 -Out D:\safe\llmd  another folder
param([string]$Out = '')
$ErrorActionPreference = 'Continue'      # docker writes progress to stderr; success is judged by the exit codes below
$root = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'env.ps1')
$composeArgs = @('--env-file', (Join-Path $root '.env'), '-f', (Join-Path $root 'docker\docker-compose.yml'))
function Compose { docker compose @composeArgs @args; if ($LASTEXITCODE -ne 0) { throw "docker compose $($args -join ' ') failed" } }

if (-not $Out) { $Out = Join-Path $root ("backups\{0}_{1}" -f $env:ODOO_DB, (Get-Date -Format 'yyyyMMdd-HHmmss')) }
if (Test-Path $Out) { throw "$Out already exists" }
New-Item -ItemType Directory -Force $Out | Out-Null

Write-Host "database $($env:ODOO_DB) -> $Out\database.dump"
Compose exec -T db pg_dump -U $env:POSTGRES_USER -Fc -f /tmp/llmd_backup.dump $env:ODOO_DB
Compose cp db:/tmp/llmd_backup.dump (Join-Path $Out 'database.dump')
Compose exec -T db rm -f /tmp/llmd_backup.dump

docker compose @composeArgs exec -T odoo test -d "/var/lib/odoo/filestore/$($env:ODOO_DB)"
if ($LASTEXITCODE -eq 0) {
    Write-Host "filestore -> $Out\filestore"
    Compose cp "odoo:/var/lib/odoo/filestore/$($env:ODOO_DB)" (Join-Path $Out 'filestore')
} else {
    Write-Host 'no filestore folder yet (nothing to copy)'
}
Write-Host "`nBackup done: $Out  (private data - keep it safe)"
