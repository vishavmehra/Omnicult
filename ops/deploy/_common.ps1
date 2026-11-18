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
$script:SchedulerSa   = "omnicult-scheduler@$($script:Project).iam.gserviceaccount.com"
$script:YoutubeSecret = 'omnicult-youtube-api-key'
# Firebase Hosting fronts omnicult-web: the browser origins the API and the bucket must accept besides the run.app URL.
$script:HostingUrls   = @("https://$($script:Project).web.app", "https://$($script:Project).firebaseapp.com")
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

function Invoke-GcloudCapture {
    # Runs gcloud and returns its stdout. Throws on a non-zero exit code and includes gcloud's own error text.
    $ErrorActionPreference = 'Continue'
    $errFile = [IO.Path]::GetTempFileName()
    try {
        $out = & $script:Gcloud @args 2>$errFile
        if ($LASTEXITCODE -ne 0) {
            $err = (Get-Content $errFile -Raw -ErrorAction SilentlyContinue)
            throw "gcloud $($args[0..2] -join ' ') failed with exit code ${LASTEXITCODE}: $err"
        }
        return ($out | Out-String).Trim()
    } finally {
        Remove-Item $errFile -ErrorAction SilentlyContinue
    }
}

function Wait-CloudBuild([hashtable]$Builds, [int]$TimeoutMinutes = 40) {
    # $Builds maps a label to a Cloud Build id. Polls until every build is finished; throws if any did not succeed.
    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $state = @{}
    foreach ($k in $Builds.Keys) { $state[$k] = '' }
    while ($true) {
        $pending = $false
        foreach ($label in @($Builds.Keys)) {
            if ($state[$label] -in 'SUCCESS', 'FAILURE', 'INTERNAL_ERROR', 'TIMEOUT', 'CANCELLED', 'EXPIRED') { continue }
            $status = Get-GcloudValue builds describe $Builds[$label] --project $script:Project --format 'value(status)'
            if (-not $status) { $status = 'UNKNOWN' }
            if ($status -ne $state[$label]) { Write-Host ("[{0}] {1}: {2}" -f (Get-Date -Format HH:mm:ss), $label, $status) }
            $state[$label] = $status
            if ($status -notin 'SUCCESS', 'FAILURE', 'INTERNAL_ERROR', 'TIMEOUT', 'CANCELLED', 'EXPIRED') { $pending = $true }
        }
        if (-not $pending) { break }
        if ((Get-Date) -gt $deadline) { throw "Cloud Build did not finish within $TimeoutMinutes minutes." }
        Start-Sleep -Seconds 15
    }
    $bad = @($state.Keys | Where-Object { $state[$_] -ne 'SUCCESS' })
    if ($bad.Count -gt 0) {
        foreach ($label in $bad) {
            Write-Host "Build '$label' ($($Builds[$label])) ended $($state[$label]). Last log lines:"
            $ErrorActionPreference = 'Continue'
            & $script:Gcloud builds log $Builds[$label] --project $script:Project 2>&1 | Select-Object -Last 40 | ForEach-Object { Write-Host "  $_" }
        }
        throw "Cloud Build failed: $($bad -join ', ')."
    }
}

function Get-ServiceUrl([string]$Name) {
    return Get-GcloudValue run services describe $Name --region $script:Region --project $script:Project --format 'value(status.url)'
}

function Get-ServiceRevision([string]$Name) {
    # The revision that currently serves, and the image it runs (digest-pinned by Cloud Run at deploy time).
    $rev = Get-GcloudValue run services describe $Name --region $script:Region --project $script:Project --format 'value(status.latestReadyRevisionName)'
    $img = Get-GcloudValue run revisions describe $rev --region $script:Region --project $script:Project --format 'value(status.imageDigest)'
    return "$rev ($img)"
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
