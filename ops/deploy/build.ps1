<#
.SYNOPSIS
  Builds the API and/or web image with Cloud Build into Artifact Registry (asia-south1/omnicult).
.EXAMPLE
  .\build.ps1 -Target all
  .\build.ps1 -Target api -Tag v1
  .\build.ps1 -Target web -AuthMode dev      # interim web image, before the Firebase sign-in code is merged
.NOTES
  Every build pushes <image>:<Tag> and <image>:latest. The web image inlines NEXT_PUBLIC_* values at build time:
  the API origin, the auth mode, and the public Firebase web config from ops/firebase-web-config.json.
#>
param(
    [ValidateSet('api', 'web', 'all')][string]$Target = 'all',
    [string]$Tag,
    [string]$ApiUrl,                 # default: the omnicult-api Cloud Run URL
    [string]$AuthMode = 'firebase'   # NEXT_PUBLIC_AUTH_MODE for the web image: firebase (final) or dev (interim)
)
. "$PSScriptRoot\_common.ps1"

if (-not $Tag) {
    $sha = (git -C $script:RepoRoot rev-parse --short HEAD).Trim()
    $Tag = "$sha-$(Get-Date -Format yyyyMMddHHmm)"
}

if ($Target -in 'api', 'all') {
    Invoke-Gcloud builds submit (Join-Path $script:RepoRoot 'backend') `
        --project $script:Project `
        --config (Join-Path $script:RepoRoot 'ops\cloudbuild\backend.yaml') `
        --substitutions "_IMAGE=$($script:ApiImage),_TAG=$Tag"
    Write-Host "API image: $($script:ApiImage):$Tag"
}

if ($Target -in 'web', 'all') {
    if (-not $ApiUrl) { $ApiUrl = Get-ServiceUrl 'omnicult-api' }
    if (-not $ApiUrl) { $ApiUrl = $script:ApiUrlDefault }
    $fb = Get-FirebaseWebConfig
    $subs = @(
        "_IMAGE=$($script:WebImage)", "_TAG=$Tag", "_API_BASE_URL=$ApiUrl", "_AUTH_MODE=$AuthMode",
        "_FIREBASE_API_KEY=$($fb.apiKey)", "_FIREBASE_AUTH_DOMAIN=$($fb.authDomain)",
        "_FIREBASE_PROJECT_ID=$($fb.projectId)", "_FIREBASE_APP_ID=$($fb.appId)"
    ) -join ','
    Invoke-Gcloud builds submit (Join-Path $script:RepoRoot 'frontend') `
        --project $script:Project `
        --config (Join-Path $script:RepoRoot 'ops\cloudbuild\frontend.yaml') `
        --substitutions $subs
    Write-Host "Web image: $($script:WebImage):$Tag (API origin $ApiUrl, auth mode $AuthMode)"
}
