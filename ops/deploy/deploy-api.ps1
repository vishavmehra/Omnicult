<#
.SYNOPSIS
  Deploys omnicult-api to Cloud Run (asia-south1): always-on CPU, 0 to 1 instances, Cloud SQL attached, secrets from
  Secret Manager, runtime identity omnicult-api. Private (Cloud Run IAM) unless -Public is given.
.EXAMPLE
  .\deploy-api.ps1                                     # final configuration: APP_ENV=production, AUTH_MODE=firebase
  .\deploy-api.ps1 -AppEnv development -AuthMode dev   # interim, before the Firebase auth code is merged
  .\deploy-api.ps1 -Public                             # the browser calls the API directly; auth is the Firebase ID token
#>
param(
    [string]$Tag = 'latest',
    [string]$AppEnv = 'production',
    [string]$AuthMode = 'firebase',
    [string]$WebUrl,                 # CORS origin; default: the omnicult-web URL
    [switch]$Public
)
. "$PSScriptRoot\_common.ps1"

if (-not $WebUrl) { $WebUrl = $script:WebUrlDefault }
$envFile = New-EnvFile @{
    APP_ENV               = $AppEnv
    AUTH_MODE             = $AuthMode
    LOG_LEVEL             = 'INFO'
    FRONTEND_ORIGINS      = $WebUrl
    ASSET_STORAGE_BACKEND = 'gcs'
    GCS_BUCKET            = $script:Bucket
    FIREBASE_PROJECT_ID   = $script:Project
    GOOGLE_GENAI_BACKEND  = 'vertex'
    GOOGLE_CLOUD_PROJECT  = $script:Project
    GOOGLE_CLOUD_LOCATION = 'global'
}
$access = if ($Public) { '--allow-unauthenticated' } else { '--no-allow-unauthenticated' }
try {
    Invoke-Gcloud run deploy omnicult-api `
        --project $script:Project --region $script:Region `
        --image "$($script:ApiImage):$Tag" `
        --service-account $script:ApiSa `
        --add-cloudsql-instances $script:SqlInstance `
        --set-secrets 'DATABASE_URL=omnicult-database-url:latest' `
        --env-vars-file $envFile `
        --port 8080 --cpu 1 --memory 1Gi --no-cpu-throttling --cpu-boost `
        --min-instances 0 --max-instances 1 --concurrency 40 --timeout 900 `
        --startup-probe 'httpGet.path=/health,httpGet.port=8080,timeoutSeconds=3,periodSeconds=5,failureThreshold=24' `
        $access
} finally {
    Remove-Item $envFile -ErrorAction SilentlyContinue
}
Write-Host "omnicult-api: $(Get-ServiceUrl 'omnicult-api')"
