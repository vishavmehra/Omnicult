<#
.SYNOPSIS
  Deploys Firebase Hosting (site omnicult-app, https://omnicult-app.web.app) as a front for the omnicult-web Cloud Run
  service: ops/firebase/firebase.json rewrites every path to omnicult-web in asia-south1. Spark plan, no cost. Also adds the
  Hosting origins to the asset bucket's CORS (ops/gcs-cors.json). Idempotent.
.NOTES
  Credentials: the existing firebase login if there is one, otherwise the gcloud application-default credentials file (sets
  GOOGLE_APPLICATION_CREDENTIALS for this process only). The API accepts the Hosting origins once deploy-api.ps1 has run
  (FRONTEND_ORIGINS). The /__/auth/* paths are served by Hosting itself, not forwarded to Cloud Run.
  Hosting never serves a static index.html (ops/firebase/public holds only 404.html), so every page comes from Cloud Run.
#>
param([switch]$SkipCors)
. "$PSScriptRoot\_common.ps1"

if (-not (Get-Command firebase -ErrorAction SilentlyContinue)) { throw 'firebase CLI not found (npm i -g firebase-tools).' }
# Prefer an existing firebase login; otherwise fall back to the gcloud application-default credentials. firebase runs through
# cmd because the PowerShell shim can crash Node 24 on Windows with a libuv assertion.
if (-not $env:GOOGLE_APPLICATION_CREDENTIALS -and ((cmd /c 'firebase login:list 2>&1' | Out-String) -notmatch 'Logged in as')) {
    $adc = Join-Path $env:APPDATA 'gcloud\application_default_credentials.json'
    if (Test-Path $adc) { $env:GOOGLE_APPLICATION_CREDENTIALS = $adc }
}
if (-not $SkipCors) {
    Invoke-Gcloud storage buckets update "gs://$($script:Bucket)" --project $script:Project --cors-file (Join-Path $script:RepoRoot 'ops\gcs-cors.json')
}
Push-Location (Join-Path $script:RepoRoot 'ops\firebase')
try {
    $ErrorActionPreference = 'Continue'
    cmd /c "firebase deploy --only hosting --project $($script:Project) --non-interactive"
    if ($LASTEXITCODE -ne 0) { throw "firebase deploy failed with exit code $LASTEXITCODE" }
} finally {
    Pop-Location
}
Write-Host "Hosting: https://$($script:Project).web.app -> omnicult-web ($($script:Region))"
