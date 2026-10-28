# Loads the package's .env into this PowerShell session and points the test tools at the LOCAL instance.
# Usage, from the package root (dot-source it):   . .\scripts\env.ps1
# setup.ps1 uses  . .\scripts\env.ps1 -Create  to make the .env first: empty or "change-me..." passwords become random local-only values.
param([switch]$Create)
$root = Split-Path $PSScriptRoot -Parent
$envFile = Join-Path $root '.env'

if (-not (Test-Path $envFile)) {
    if (-not $Create) { throw '.env is missing - run .\scripts\setup.ps1 first (or copy your existing local .env to the package root).' }
    function New-Secret { -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ }) }
    $lines = Get-Content (Join-Path $root '.env.example') | ForEach-Object {
        if ($_ -match '^(POSTGRES_PASSWORD|ODOO_PASSWORD)=(change-me.*)?$') { "$($Matches[1])=$(New-Secret)" } else { $_ }
    }
    Set-Content -Path $envFile -Value $lines -Encoding ascii
    Write-Host 'created .env with random local-only passwords'
}

Get-Content $envFile | Where-Object { $_ -match '^\s*[^#;\s][^=]*=' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    Set-Item -Path ("Env:" + $k.Trim()) -Value $v.Trim()
}
$env:ODOO_URL = "http://127.0.0.1:$($env:ODOO_PORT)"
# a local run never needs (or sees) the live site's key, and live writes stay locked
Remove-Item Env:MCP_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ALLOW_PRODUCTION -ErrorAction SilentlyContinue
$env:PYTHONIOENCODING = 'utf-8'
