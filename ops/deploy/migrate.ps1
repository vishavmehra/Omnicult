<#
.SYNOPSIS
  Creates or updates the Cloud Run Job omnicult-migrate (alembic upgrade head) and runs it to completion.
.NOTES
  Run it after build.ps1 -Target api and before deploy-api.ps1 whenever a migration was added. The job connects to
  Cloud SQL through the Cloud SQL attachment (unix socket) with DATABASE_URL from Secret Manager. The settings loader
  refuses AUTH_MODE=dev when APP_ENV=production, so the job needs the same -AppEnv/-AuthMode as the service.
  -JobArgs and -JobCommand exist for one-off checks (for example a database probe); the defaults are the migration.
#>
param(
    [string]$Tag = 'latest',
    [string]$AppEnv = 'production',
    [string]$AuthMode = 'firebase',
    [string]$JobCommand = 'alembic',
    [string]$JobArgs = 'upgrade,head',   # comma-separated
    [switch]$NoExecute
)
. "$PSScriptRoot\_common.ps1"

$envFile = New-EnvFile @{ APP_ENV = $AppEnv; AUTH_MODE = $AuthMode; LOG_LEVEL = 'INFO' }
try {
    Invoke-Gcloud run jobs deploy omnicult-migrate `
        --project $script:Project --region $script:Region `
        --image "$($script:ApiImage):$Tag" `
        --service-account $script:ApiSa `
        --set-cloudsql-instances $script:SqlInstance `
        --set-secrets 'DATABASE_URL=omnicult-database-url:latest' `
        --env-vars-file $envFile `
        --command $JobCommand --args $JobArgs `
        --cpu 1 --memory 512Mi --max-retries 0 --task-timeout 600s
} finally {
    Remove-Item $envFile -ErrorAction SilentlyContinue
}
if (-not $NoExecute) {
    Invoke-Gcloud run jobs execute omnicult-migrate --project $script:Project --region $script:Region --wait
}
