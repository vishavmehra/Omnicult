<#
.SYNOPSIS
  Checks /health and /ready on omnicult-api. Sends an identity token (your gcloud account must hold run.invoker, which
  project owners do), so it works whether the service is private or public. /ready is 200 for ready or degraded and 503
  for not_ready (database unreachable).
#>
param([string]$ApiUrl)
. "$PSScriptRoot\_common.ps1"

if (-not $ApiUrl) { $ApiUrl = Get-ServiceUrl 'omnicult-api' }
$token = (& $script:Gcloud auth print-identity-token | Out-String).Trim()
$headers = @{ Authorization = "Bearer $token" }
$failed = $false
foreach ($path in '/health', '/ready') {
    try {
        $r = Invoke-WebRequest -Uri "$ApiUrl$path" -Headers $headers -UseBasicParsing
        Write-Host "$path -> $($r.StatusCode) $($r.Content)"
    } catch {
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 'no response' }
        Write-Host "$path -> FAILED ($code)"
        $failed = $true
    }
}
if ($failed) { exit 1 }
