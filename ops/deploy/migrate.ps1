<#
.SYNOPSIS
  Migrates Cloud SQL to head and loads the reference data: creates or updates two Cloud Run Jobs from the API image and
  runs them to completion, in order:
    omnicult-migrate   alembic upgrade head          (schema; additive, safe to re-run)
    omnicult-seed      python -m scripts.seed_all   (runs scripts.seed_reference_data: India languages, regions, language
                       profiles, curated moments and the country pack; then scripts.seed_demo_claims when the image has
                       it. Both are idempotent upserts, safe to re-run)
.EXAMPLE
  .\migrate.ps1                  # migrate, then seed
  .\migrate.ps1 -Backup          # take an on-demand Cloud SQL backup first (do this before a risky migration)
  .\migrate.ps1 -SkipSeed        # schema only
  .\migrate.ps1 -NoExecute       # only create or update the jobs
.NOTES
  Run it after build.ps1 and before deploy-api.ps1. Both jobs connect through the Cloud SQL attachment (unix socket)
  with DATABASE_URL from Secret Manager. The settings loader refuses AUTH_MODE=dev when APP_ENV=production, so the jobs
  carry the same -AppEnv/-AuthMode as the service. -JobCommand and -JobArgs (comma-separated) reconfigure the migrate
  job for a one-off check (for example a database probe); the defaults are the migration.
  The ASCI ad-code index is not table-backed: it ships inside the image (app/reference/ad_codes_asci.json), so it has no
  seed step. Pulse's sample dataset is generated in code and demo projects are created per user by
  POST /api/v1/projects/demo, so neither needs seeding either.
#>
param(
    [string]$Tag = 'latest',
    [string]$AppEnv = 'production',
    [string]$AuthMode = 'firebase',
    [string]$JobCommand = 'alembic',
    [string]$JobArgs = 'upgrade,head',   # comma-separated
    [switch]$Backup,
    [switch]$SkipSeed,
    [switch]$NoExecute
)
. "$PSScriptRoot\_common.ps1"

function Set-CloudRunJob([string]$Name, [string]$Command, [string]$Arguments, [string]$Image) {
    $envFile = New-EnvFile @{ APP_ENV = $AppEnv; AUTH_MODE = $AuthMode; LOG_LEVEL = 'INFO'; FIREBASE_PROJECT_ID = $script:Project }
    try {
        Invoke-Gcloud run jobs deploy $Name `
            --project $script:Project --region $script:Region `
            --image $Image `
            --service-account $script:ApiSa `
            --set-cloudsql-instances $script:SqlInstance `
            --set-secrets 'DATABASE_URL=omnicult-database-url:latest' `
            --env-vars-file $envFile `
            --command $Command "--args=$Arguments" `
            --cpu 1 --memory 512Mi --max-retries 0 --task-timeout 600s
    } finally {
        Remove-Item $envFile -ErrorAction SilentlyContinue
    }
}

function Invoke-CloudRunJob([string]$Name) {
    # Runs the job to completion; on failure prints the job's last log lines before throwing.
    $ErrorActionPreference = 'Continue'
    & $script:Gcloud run jobs execute $Name --project $script:Project --region $script:Region --wait
    $code = $LASTEXITCODE
    $execution = Get-GcloudValue run jobs executions list --job $Name --project $script:Project --region $script:Region --limit 1 --format 'value(name)'
    Write-Host "$Name execution: $execution (exit code $code)"
    # Cloud Logging lags the execution by up to a minute; ask a few times before giving up on the log lines.
    $filter = "resource.type=""cloud_run_job"" AND labels.""run.googleapis.com/execution_name""=""$execution"""
    $lines = $null
    for ($try = 0; $try -lt 4 -and -not $lines; $try++) {
        if ($try -gt 0) { Start-Sleep -Seconds 15 }
        $lines = Get-GcloudValue logging read $filter --project $script:Project --limit 60 --order desc --format 'value(textPayload)'
    }
    if ($lines) {
        $rows = @($lines -split "`n" | Where-Object { $_ } | Select-Object -First 25)
        [array]::Reverse($rows)   # newest first from Cloud Logging; print oldest first
        $rows | ForEach-Object { Write-Host "  | $_" }
    } else {
        Write-Host '  (no log lines available yet; read them with: gcloud logging read ...)'
    }
    if ($code -ne 0) { throw "Cloud Run job $Name failed (execution $execution)." }
}

$image = "$($script:ApiImage):$Tag"

if ($Backup) {
    Invoke-Gcloud sql backups create --instance omnicult-db --project $script:Project --description "before migrate $(Get-Date -Format yyyyMMdd-HHmm)"
}

Set-CloudRunJob 'omnicult-migrate' $JobCommand $JobArgs $image
if (-not $SkipSeed) { Set-CloudRunJob 'omnicult-seed' 'python' '-m,scripts.seed_all' $image }

if (-not $NoExecute) {
    Invoke-CloudRunJob 'omnicult-migrate'
    if (-not $SkipSeed) { Invoke-CloudRunJob 'omnicult-seed' }
}
