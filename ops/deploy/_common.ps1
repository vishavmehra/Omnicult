# Shared settings and helpers for the ops/deploy scripts (dot-source it: `. "$PSScriptRoot\_common.ps1"`).
# Nothing here is secret: resource names only. Secrets stay in Secret Manager and are referenced by name.
$ErrorActionPreference = 'Stop'

$script:Project       = 'omnicult-app'
$script:ProjectNumber = '671429087856'
$script:Region        = 'asia-south1'
$script:Registry      = "$($script:Region)-docker.pkg.dev/$($script:Project)/omnicult"
$script:ApiImage      = "$($script:Registry)/omnicult-api"
$script:WebImage      = "$($script:Registry)/omnicult-web"
$script:ApiSa         = "omnicult-api@$($script:Project).iam.gserviceaccount.com"
$script:WebSa         = "omnicult-web@$($script:Project).iam.gserviceaccount.com"
$script:SqlInstance   = "$($script:Project):$($script:Region):omnicult-db"
$script:Bucket        = 'omnicult-app-assets'
$script:RepoRoot      = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
# Cloud Run's deterministic URL form (SERVICE-PROJECT_NUMBER.REGION.run.app), known before the first deploy.
$script:ApiUrlDefault = "https://omnicult-api-$($script:ProjectNumber).$($script:Region).run.app"
$script:WebUrlDefault = "https://omnicult-web-$($script:ProjectNumber).$($script:Region).run.app"

$script:Gcloud = (Get-Command gcloud.cmd -ErrorAction SilentlyContinue).Source
if (-not $script:Gcloud) { $script:Gcloud = Join-Path $env:LOCALAPPDATA 'Google\google-cloud-sdk\bin\gcloud.cmd' }

function Invoke-Gcloud {
    # Runs gcloud; stdout and stderr go to the console. Throws on a non-zero exit code. gcloud writes progress to
    # stderr, which Windows PowerShell 5.1 would turn into a terminating error under 'Stop', so relax it here.
    $ErrorActionPreference = 'Continue'
    & $script:Gcloud @args
    if ($LASTEXITCODE -ne 0) { throw "gcloud $($args[0..2] -join ' ') failed with exit code $LASTEXITCODE" }
}

function Get-GcloudValue {
    # Runs gcloud and returns its trimmed stdout, or $null when it fails (for example, a service that does not exist yet).
    $ErrorActionPreference = 'Continue'
    $out = & $script:Gcloud @args 2>$null
    if ($LASTEXITCODE -ne 0) { return $null }
    return ($out | Out-String).Trim()
}

function Get-ServiceUrl([string]$Name) {
    return Get-GcloudValue run services describe $Name --region $script:Region --project $script:Project --format 'value(status.url)'
}

function Get-FirebaseWebConfig {
    return Get-Content (Join-Path $script:RepoRoot 'ops\firebase-web-config.json') -Raw | ConvertFrom-Json
}

function New-EnvFile([hashtable]$Values) {
    # A YAML file for `gcloud run ... --env-vars-file` (safe for values that contain commas). Delete it after use.
    $path = Join-Path ([IO.Path]::GetTempPath()) ('omnicult-env-' + [guid]::NewGuid().ToString('N') + '.yaml')
    $lines = foreach ($key in ($Values.Keys | Sort-Object)) {
        '{0}: "{1}"' -f $key, ([string]$Values[$key]).Replace('\', '\\').Replace('"', '\"')
    }
    Set-Content -Path $path -Value $lines -Encoding ascii
    return $path
}
