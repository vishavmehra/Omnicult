<#
.SYNOPSIS
  Builds the API and/or web image with Cloud Build into Artifact Registry (asia-south1/omnicult). Nothing builds
  locally: the source is uploaded and Cloud Build does the work. With -Target all, both builds run at the same time.
.EXAMPLE
  .\build.ps1                       # both images, tag <git sha>-<timestamp>, also :latest
  .\build.ps1 -Target api -Tag v1
  .\build.ps1 -Target web -AuthMode dev      # interim web image (no Firebase sign-in)
.NOTES
  Every build pushes <image>:<Tag> and <image>:latest. The later steps default to :latest, so a plain
  `build.ps1; migrate.ps1; deploy-api.ps1 -Public; deploy-web.ps1; smoke.ps1` deploys what was just built.
  The web image inlines NEXT_PUBLIC_* values at build time: the API origin, the auth mode and the public Firebase web
  config from ops/firebase-web-config.json (public identifiers, not secrets). Changing the API URL needs a web rebuild.
  The API build fails (by design) when ffmpeg, the Noto fonts or Pillow's raqm shaping are missing from the image.
#>
param(
    [ValidateSet('api', 'web', 'all')][string]$Target = 'all',
    [string]$Tag,
    [string]$ApiUrl,                 # default: the omnicult-api Cloud Run URL
    [string]$AuthMode = 'firebase',  # NEXT_PUBLIC_AUTH_MODE for the web image: firebase (final) or dev (interim)
    [switch]$NoWait                  # submit and return the build ids without waiting
)
. "$PSScriptRoot\_common.ps1"

if (-not $Tag) {
    $sha = (git -C $script:RepoRoot rev-parse --short HEAD).Trim()
    $Tag = "$sha-$(Get-Date -Format yyyyMMddHHmm)"
}

$builds = @{}

if ($Target -in 'api', 'all') {
    $builds['api'] = Invoke-GcloudCapture builds submit (Join-Path $script:RepoRoot 'backend') `
        --project $script:Project --async --format 'value(id)' `
        --config (Join-Path $script:RepoRoot 'ops\cloudbuild\backend.yaml') `
        --substitutions "_IMAGE=$($script:ApiImage),_TAG=$Tag"
    Write-Host "Submitted API build $($builds['api']) -> $($script:ApiImage):$Tag"
}

if ($Target -in 'web', 'all') {
    # The deterministic URL form (SERVICE-PROJECT_NUMBER.REGION.run.app), not the hash-style alias that `status.url`
    # now reports: it is the one in CORS, in Firebase's authorized domains and in the runbook.
    if (-not $ApiUrl) { $ApiUrl = $script:ApiUrlDefault }
    $fb = Get-FirebaseWebConfig
    $subs = @(
        "_IMAGE=$($script:WebImage)", "_TAG=$Tag", "_API_BASE_URL=$ApiUrl", "_AUTH_MODE=$AuthMode",
        "_FIREBASE_API_KEY=$($fb.apiKey)", "_FIREBASE_AUTH_DOMAIN=$($fb.authDomain)",
        "_FIREBASE_PROJECT_ID=$($fb.projectId)", "_FIREBASE_APP_ID=$($fb.appId)"
    ) -join ','
    $builds['web'] = Invoke-GcloudCapture builds submit (Join-Path $script:RepoRoot 'frontend') `
        --project $script:Project --async --format 'value(id)' `
        --config (Join-Path $script:RepoRoot 'ops\cloudbuild\frontend.yaml') `
        --substitutions $subs
    Write-Host "Submitted web build $($builds['web']) -> $($script:WebImage):$Tag (API origin $ApiUrl, auth mode $AuthMode)"
}

if ($NoWait) { return }
Wait-CloudBuild $builds
if ($builds.ContainsKey('api')) { Write-Host "API image ready: $($script:ApiImage):$Tag" }
if ($builds.ContainsKey('web')) { Write-Host "Web image ready: $($script:WebImage):$Tag" }
