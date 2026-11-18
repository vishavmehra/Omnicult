<#
.SYNOPSIS
  Deploys omnicult-web (the Next.js standalone image) to Cloud Run (asia-south1), public, 0 to 2 instances. The API
  origin, the auth mode and the Firebase web config are baked in at image build time (build.ps1 -Target web), so this
  script only runs the image.
#>
param([string]$Tag = 'latest')
. "$PSScriptRoot\_common.ps1"

Invoke-Gcloud run deploy omnicult-web `
    --project $script:Project --region $script:Region `
    --image "$($script:WebImage):$Tag" `
    --service-account $script:WebSa `
    --port 8080 --cpu 1 --memory 512Mi --min-instances 0 --max-instances 2 --concurrency 80 --timeout 60 `
    --allow-unauthenticated
Write-Host "omnicult-web: $($script:WebUrlDefault)"
Write-Host "revision:     $(Get-ServiceRevision 'omnicult-web')"
