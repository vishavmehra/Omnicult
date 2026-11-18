<#
.SYNOPSIS
  Creates the Secret Manager secret omnicult-youtube-api-key from YOUTUBE_API_KEY in a local env file, and lets the
  API's service account read it. deploy-api.ps1 mounts it as YOUTUBE_API_KEY. Idempotent: an existing secret that already
  has a version is left alone unless -Rotate is given. The value is never printed and never written anywhere but the
  secret (a temporary file holds it for the gcloud call and is deleted at once).
.EXAMPLE
  .\secrets.ps1
  .\secrets.ps1 -Rotate          # add a new version from the env file
#>
param(
    [string]$EnvFile = (Join-Path $env:USERPROFILE '.omnicult\omnicult.env'),
    [switch]$Rotate
)
. "$PSScriptRoot\_common.ps1"

$name = $script:YoutubeSecret
$exists = [bool](Get-GcloudValue secrets describe $name --project $script:Project --format 'value(name)')
$hasVersion = $exists -and [bool](Get-GcloudValue secrets versions list $name --project $script:Project --filter 'state=ENABLED' --limit 1 --format 'value(name)')

if (-not $exists) {
    Invoke-Gcloud secrets create $name --project $script:Project --replication-policy user-managed --locations $script:Region
}
if (-not $hasVersion -or $Rotate) {
    if (-not (Test-Path $EnvFile)) { throw "Env file not found: $EnvFile" }
    $line = Get-Content $EnvFile | Where-Object { $_ -match '^\s*YOUTUBE_API_KEY\s*=' } | Select-Object -First 1
    $value = if ($line) { ($line -replace '^\s*YOUTUBE_API_KEY\s*=\s*', '').Trim().Trim('"').Trim("'") } else { '' }
    if (-not $value) { throw "YOUTUBE_API_KEY is missing or empty in $EnvFile" }
    $tmp = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($tmp, $value, (New-Object Text.UTF8Encoding($false)))   # no trailing newline
        Invoke-Gcloud secrets versions add $name --project $script:Project --data-file $tmp
    } finally {
        Remove-Item $tmp -ErrorAction SilentlyContinue
        $value = $null
    }
} else {
    Write-Host "$name already has a version; left unchanged (use -Rotate to add one)."
}
Invoke-Gcloud secrets add-iam-policy-binding $name --project $script:Project `
    --member "serviceAccount:$($script:ApiSa)" --role roles/secretmanager.secretAccessor --condition None | Out-Null
Write-Host "$name ready; readable by $($script:ApiSa)."
