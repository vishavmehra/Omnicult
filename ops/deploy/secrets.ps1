<#
.SYNOPSIS
  Creates the Secret Manager secrets omnicult-youtube-api-key (from YOUTUBE_API_KEY), omnicult-data-gov-in-api-key (from
  DATA_GOV_IN_API_KEY), omnicult-data-commons-api-key (from DATA_COMMONS_API_KEY: a Google Data Commons key) and
  omnicult-google-public-api-key (from GOOGLE_PUBLIC_API_KEY: an API key restricted to the Calendar and Knowledge Graph Search
  APIs) out of a local env file, and lets the API's service account read them. deploy-api.ps1 mounts them as YOUTUBE_API_KEY,
  DATA_GOV_IN_API_KEY (only with -DataGovKey), DATA_COMMONS_API_KEY and GOOGLE_PUBLIC_API_KEY. Idempotent: an existing secret that
  already has a version is left alone unless -Rotate is given. The YouTube key is required; the others are created only when the
  env file has them. A
  value is never printed and never written anywhere but the secret (a temporary file holds it for the gcloud call and is
  deleted at once).
.EXAMPLE
  .\secrets.ps1
  .\secrets.ps1 -Rotate          # add a new version from the env file
#>
param(
    [string]$EnvFile = (Join-Path $env:USERPROFILE '.omnicult\omnicult.env'),
    [switch]$Rotate
)
. "$PSScriptRoot\_common.ps1"

function Set-ApiSecret {
    param([string]$Name, [string]$Variable, [switch]$Optional)
    $exists = [bool](Get-GcloudValue secrets describe $Name --project $script:Project --format 'value(name)')
    $hasVersion = $exists -and [bool](Get-GcloudValue secrets versions list $Name --project $script:Project --filter 'state=ENABLED' --limit 1 --format 'value(name)')
    $value = ''
    if (-not $hasVersion -or $Rotate) {
        if (-not (Test-Path $EnvFile)) { if ($Optional) { Write-Host "$Name skipped: $EnvFile not found."; return }; throw "Env file not found: $EnvFile" }
        $line = Get-Content $EnvFile | Where-Object { $_ -match "^\s*$Variable\s*=" } | Select-Object -First 1
        $value = if ($line) { ($line -replace "^\s*$Variable\s*=\s*", '').Trim().Trim('"').Trim("'") } else { '' }
        if (-not $value) {
            if ($Optional) { Write-Host "$Name skipped: $Variable is not in $EnvFile."; return }
            throw "$Variable is missing or empty in $EnvFile"
        }
    }
    if (-not $exists) {
        Invoke-Gcloud secrets create $Name --project $script:Project --replication-policy user-managed --locations $script:Region
    }
    if ($value) {
        $tmp = [IO.Path]::GetTempFileName()
        try {
            [IO.File]::WriteAllText($tmp, $value, (New-Object Text.UTF8Encoding($false)))   # no trailing newline
            Invoke-Gcloud secrets versions add $Name --project $script:Project --data-file $tmp
        } finally {
            Remove-Item $tmp -ErrorAction SilentlyContinue
            $value = $null
        }
    } else {
        Write-Host "$Name already has a version; left unchanged (use -Rotate to add one)."
    }
    Invoke-Gcloud secrets add-iam-policy-binding $Name --project $script:Project `
        --member "serviceAccount:$($script:ApiSa)" --role roles/secretmanager.secretAccessor --condition None | Out-Null
    Write-Host "$Name ready; readable by $($script:ApiSa)."
}

Set-ApiSecret -Name $script:YoutubeSecret -Variable 'YOUTUBE_API_KEY'
Set-ApiSecret -Name $script:DataGovSecret -Variable 'DATA_GOV_IN_API_KEY' -Optional
Set-ApiSecret -Name $script:DataCommonsSecret -Variable 'DATA_COMMONS_API_KEY' -Optional
Set-ApiSecret -Name $script:GooglePublicSecret -Variable 'GOOGLE_PUBLIC_API_KEY' -Optional
