<#
.SYNOPSIS
  Creates or updates the three Cloud Scheduler HTTP jobs that call the API's internal endpoints with an OIDC token, and the
  service account and permissions they need. Idempotent. Run it after deploy-api.ps1 (the endpoints must exist).
    omnicult-pulse-evaluate-alerts POST /api/v1/internal/pulse/evaluate-alerts    daily at 06:00 Asia/Kolkata
    omnicult-weekly-digest  POST /api/v1/internal/digest/generate-weekly   Mondays at 06:00 Asia/Kolkata
    omnicult-signals-refresh POST /api/v1/internal/signals/refresh         daily at 05:30 Asia/Kolkata
.NOTES
  The caller is the service account omnicult-scheduler (created here, no project roles). The API checks the token against
  SCHEDULER_SERVICE_ACCOUNT (that account) and SCHEDULER_AUDIENCE (the API URL), both set by deploy-api.ps1. The account is
  also granted roles/run.invoker on omnicult-api, which matters only if the service is ever made private. Enables the Cloud
  Scheduler API (free tier: 3 jobs per billing account; this uses all 3).
  Use -Pause to create or leave the jobs paused, -Resume to enable them.
#>
param([switch]$Pause, [switch]$Resume)
. "$PSScriptRoot\_common.ps1"

Invoke-Gcloud services enable cloudscheduler.googleapis.com --project $script:Project

$saName = $script:SchedulerSa.Split('@')[0]
if (-not (Get-GcloudValue iam service-accounts describe $script:SchedulerSa --project $script:Project --format 'value(email)')) {
    Invoke-Gcloud iam service-accounts create $saName --project $script:Project --display-name 'Omnicult Cloud Scheduler caller'
}
Invoke-Gcloud run services add-iam-policy-binding omnicult-api --project $script:Project --region $script:Region `
    --member "serviceAccount:$($script:SchedulerSa)" --role roles/run.invoker | Out-Null

$jobs = @(
    @{ Name = 'omnicult-pulse-evaluate-alerts'; Schedule = '0 6 * * *'; Path = '/api/v1/internal/pulse/evaluate-alerts';  Desc = 'Omnicult: evaluate Live Pulse alerts (daily 06:00 IST)' },
    @{ Name = 'omnicult-weekly-digest'; Schedule = '0 6 * * 1'; Path = '/api/v1/internal/digest/generate-weekly'; Desc = 'Omnicult: generate the weekly digest (Mondays 06:00 IST)' },
    @{ Name = 'omnicult-signals-refresh'; Schedule = '30 5 * * *'; Path = '/api/v1/internal/signals/refresh'; Desc = 'Omnicult: refresh Search pulse and State facts (daily 05:30 IST)' }
)
foreach ($job in $jobs) {
    $exists = [bool](Get-GcloudValue scheduler jobs describe $job.Name --project $script:Project --location $script:Region --format 'value(name)')
    $verb = if ($exists) { 'update' } else { 'create' }
    Invoke-Gcloud scheduler jobs $verb http $job.Name --project $script:Project --location $script:Region `
        --schedule $job.Schedule --time-zone 'Asia/Kolkata' `
        --uri "$($script:ApiUrlDefault)$($job.Path)" --http-method POST `
        --oidc-service-account-email $script:SchedulerSa --oidc-token-audience $script:ApiUrlDefault `
        --attempt-deadline 300s --description $job.Desc
    if ($Pause) { Invoke-Gcloud scheduler jobs pause $job.Name --project $script:Project --location $script:Region }
    if ($Resume) { Invoke-Gcloud scheduler jobs resume $job.Name --project $script:Project --location $script:Region }
}
Invoke-Gcloud scheduler jobs list --project $script:Project --location $script:Region --format 'table(name.basename(),schedule,timeZone,state,httpTarget.uri)'
