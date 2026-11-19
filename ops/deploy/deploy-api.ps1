<#
.SYNOPSIS
  Deploys omnicult-api to Cloud Run (asia-south1): always-on CPU (the run engine works in the background), 0 to 1
  instances, Cloud SQL attached, secrets from Secret Manager, runtime identity omnicult-api. Private (Cloud Run IAM)
  unless -Public is given.
.EXAMPLE
  .\deploy-api.ps1 -Public                              # production: the browser calls the API directly; authorization
                                                        # is enforced in the app (Firebase ID token), not by Cloud Run IAM
  .\deploy-api.ps1 -AppEnv development -AuthMode dev    # interim, never public
.NOTES
  Environment (none of it secret): APP_ENV, AUTH_MODE, FIREBASE_PROJECT_ID, FRONTEND_ORIGINS (CORS, the web URL),
  ASSET_STORAGE_BACKEND=gcs with GCS_BUCKET, GOOGLE_GENAI_BACKEND=vertex, GOOGLE_CLOUD_PROJECT,
  GOOGLE_CLOUD_LOCATION=global, BIGQUERY_PROJECT, WIKIMEDIA_USER_AGENT, SCHEDULER_SERVICE_ACCOUNT and SCHEDULER_AUDIENCE (the Cloud Scheduler
  OIDC caller and the audience the internal endpoints expect: the API URL). FRONTEND_ORIGINS lists the web URL and the
  Firebase Hosting origins. Secrets from Secret Manager: DATABASE_URL (omnicult-database-url) and YOUTUBE_API_KEY
  (omnicult-youtube-api-key; create it with secrets.ps1 first).
  Vertex AI and Cloud Storage use the runtime service account (Application Default Credentials); no key exists.
  Run migrate.ps1 first when a migration was added. -Public with AUTH_MODE=dev is refused here.
#>
param(
    [string]$Tag = 'latest',
    [string]$AppEnv = 'production',
    [string]$AuthMode = 'firebase',
    [string]$WebUrl,                 # CORS origin; default: the omnicult-web URL
    [string]$WikimediaUserAgent,     # default: Omnicult/0.1 (<web URL>) python-httpx
    [switch]$Public
)
. "$PSScriptRoot\_common.ps1"

if ($Public -and $AuthMode -eq 'dev') { throw 'Refusing -Public with AUTH_MODE=dev: anyone could use a dev token.' }
if (-not $WebUrl) { $WebUrl = $script:WebUrlDefault }
$secretCheck = Get-GcloudValue secrets describe $script:YoutubeSecret --project $script:Project --format 'value(name)'
if (-not $secretCheck) { throw "Secret $($script:YoutubeSecret) does not exist. Run ops\deploy\secrets.ps1 first." }
if (-not $WikimediaUserAgent) { $WikimediaUserAgent = "Omnicult/0.1 ($WebUrl) python-httpx" }
$envFile = New-EnvFile @{
    APP_ENV               = $AppEnv
    AUTH_MODE             = $AuthMode
    LOG_LEVEL             = 'INFO'
    FRONTEND_ORIGINS      = (@($WebUrl) + $script:HostingUrls) -join ','
    ASSET_STORAGE_BACKEND = 'gcs'
    GCS_BUCKET            = $script:Bucket
    FIREBASE_PROJECT_ID   = $script:Project
    GOOGLE_GENAI_BACKEND  = 'vertex'
    GOOGLE_CLOUD_PROJECT  = $script:Project
    GOOGLE_CLOUD_LOCATION = 'global'
    WIKIMEDIA_USER_AGENT  = $WikimediaUserAgent
    SCHEDULER_SERVICE_ACCOUNT = $script:SchedulerSa
    SCHEDULER_AUDIENCE    = $script:ApiUrlDefault
    BIGQUERY_PROJECT      = $script:Project
}
# Search pulse reads Google's public Trends dataset in BigQuery: the runtime account only needs to run query jobs in this
# project (the dataset is public). Idempotent; the API is enabled once with `gcloud services enable bigquery.googleapis.com`.
Invoke-Gcloud projects add-iam-policy-binding $script:Project `
    --member "serviceAccount:$($script:ApiSa)" --role roles/bigquery.jobUser --condition None | Out-Null
$access = if ($Public) { '--allow-unauthenticated' } else { '--no-allow-unauthenticated' }
try {
    Invoke-Gcloud run deploy omnicult-api `
        --project $script:Project --region $script:Region `
        --image "$($script:ApiImage):$Tag" `
        --service-account $script:ApiSa `
        --add-cloudsql-instances $script:SqlInstance `
        --set-secrets "DATABASE_URL=omnicult-database-url:latest,YOUTUBE_API_KEY=$($script:YoutubeSecret):latest" `
        --env-vars-file $envFile `
        --port 8080 --cpu 1 --memory 1Gi --no-cpu-throttling --cpu-boost `
        --min-instances 0 --max-instances 1 --concurrency 40 --timeout 900 `
        --startup-probe 'httpGet.path=/health,httpGet.port=8080,timeoutSeconds=3,periodSeconds=5,failureThreshold=24' `
        $access
} finally {
    Remove-Item $envFile -ErrorAction SilentlyContinue
}
Write-Host "omnicult-api: $($script:ApiUrlDefault)"
Write-Host "revision:     $(Get-ServiceRevision 'omnicult-api')"
