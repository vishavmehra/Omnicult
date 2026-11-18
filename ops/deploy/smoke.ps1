<#
.SYNOPSIS
  Smoke test of the live Omnicult deployment (API and web). Exits 1 if any check fails.
.DESCRIPTION
  API (no token needed):  /health, /ready, docs switched off, no token = 401, a dev token is refused in production,
                          CORS preflight from the web origin (and refusal for a foreign origin).
  Web:                    landing page 200, app shell 200, sign-in page 200, and the built bundle really points at the
                          API URL and the Firebase project.
  Signed in:              an anonymous Firebase sign-in through the Identity Toolkit REST API (the public web API key
                          from ops/firebase-web-config.json), then with that ID token: workspace bootstrap (GET /me),
                          reference data (36 regions), POST /projects/demo, list campaigns, an anonymous user cannot
                          create a live project (403), and a second user cannot read the first user's project (404).
  Clean-up:               the demo project is archived and both anonymous Firebase users are deleted (-KeepData skips
                          this). The `users` rows the API created for them stay; they are harmless.
  No token or secret is ever printed.
.EXAMPLE
  .\smoke.ps1
  .\smoke.ps1 -Hosting          # plus the Firebase Hosting front (after deploy-hosting.ps1)
  .\smoke.ps1 -SkipAuth          # unauthenticated checks only (no Firebase sign-in, no database writes)
#>
param(
    [string]$ApiUrl,
    [string]$WebUrl,
    [switch]$SkipAuth,
    [switch]$Hosting,                # also check Firebase Hosting (https://omnicult-app.web.app) in front of the web service
    [switch]$KeepData
)
. "$PSScriptRoot\_common.ps1"
Add-Type -AssemblyName System.Net.Http

if (-not $ApiUrl) { $ApiUrl = $script:ApiUrlDefault }
if (-not $WebUrl) { $WebUrl = $script:WebUrlDefault }
$ApiUrl = $ApiUrl.TrimEnd('/'); $WebUrl = $WebUrl.TrimEnd('/')
$fb = Get-FirebaseWebConfig

$handler = New-Object System.Net.Http.HttpClientHandler
$handler.AllowAutoRedirect = $false
$http = New-Object System.Net.Http.HttpClient($handler)
$http.Timeout = [TimeSpan]::FromSeconds(90)

function Send-Http {
    # Returns Status (int), Body (string) and Headers (lowercase name -> value). Never throws on an HTTP error status.
    param([string]$Method, [string]$Url, [hashtable]$Headers = @{}, [string]$Body = $null)
    $request = New-Object System.Net.Http.HttpRequestMessage ([System.Net.Http.HttpMethod]::new($Method)), $Url
    foreach ($key in $Headers.Keys) { [void]$request.Headers.TryAddWithoutValidation($key, [string]$Headers[$key]) }
    if ($Body) { $request.Content = New-Object System.Net.Http.StringContent($Body, [Text.Encoding]::UTF8, 'application/json') }
    try {
        $response = $http.SendAsync($request).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $map = @{}
        foreach ($h in $response.Headers) { $map[$h.Key.ToLowerInvariant()] = ($h.Value -join ', ') }
        foreach ($h in $response.Content.Headers) { $map[$h.Key.ToLowerInvariant()] = ($h.Value -join ', ') }
        return [pscustomobject]@{ Status = [int]$response.StatusCode; Body = $text; Headers = $map }
    } catch {
        return [pscustomobject]@{ Status = 0; Body = $_.Exception.Message; Headers = @{} }
    }
}

function ConvertFrom-JsonSafe([string]$Text) {
    try { return $Text | ConvertFrom-Json } catch { return $null }
}

$results = New-Object System.Collections.Generic.List[object]
function Test-Check([string]$Name, [bool]$Pass, [string]$Detail = '') {
    $results.Add([pscustomobject]@{ Name = $Name; Pass = $Pass; Detail = $Detail })
    Write-Host ("{0,-6} {1}{2}" -f $(if ($Pass) { 'PASS' } else { 'FAIL' }), $Name, $(if ($Detail) { "  ($Detail)" } else { '' }))
}

function Get-AuthHeaders([string]$IdToken) { return @{ Authorization = "Bearer $IdToken" } }

Write-Host "API: $ApiUrl"
Write-Host "Web: $WebUrl"
Write-Host ''

# ---- API without a token ---------------------------------------------------------------------------------------------
$r = Send-Http GET "$ApiUrl/health"
Test-Check 'api /health is public and ok' ($r.Status -eq 200 -and (ConvertFrom-JsonSafe $r.Body).status -eq 'ok') "HTTP $($r.Status)"

$r = Send-Http GET "$ApiUrl/ready"
$ready = ConvertFrom-JsonSafe $r.Body
$readyDetail = if ($ready) { "status=$($ready.status), database=$($ready.dependencies.database), llm_provider=$($ready.dependencies.llm_provider), qloo=$($ready.dependencies.qloo)" } else { "HTTP $($r.Status)" }
Test-Check 'api /ready: database available' ($r.Status -eq 200 -and $ready.dependencies.database -eq 'available') $readyDetail
Test-Check 'api /ready: Google (Vertex) model provider configured' ($ready -and $ready.dependencies.llm_provider -eq 'configured') 'configuration only, no model call is made'

$r = Send-Http GET "$ApiUrl/docs"
Test-Check 'api interactive docs are off (production)' ($r.Status -eq 404) "HTTP $($r.Status)"

$r = Send-Http GET "$ApiUrl/api/v1/me"
Test-Check 'api rejects a request with no token' ($r.Status -eq 401) "HTTP $($r.Status)"

$r = Send-Http GET "$ApiUrl/api/v1/me" (Get-AuthHeaders 'dev-smoke')
Test-Check 'api refuses a dev token in production' ($r.Status -eq 401) "HTTP $($r.Status)"

$r = Send-Http GET "$ApiUrl/api/v1/me" (Get-AuthHeaders 'not.a.jwt')
Test-Check 'api refuses a malformed token' ($r.Status -eq 401) "HTTP $($r.Status)"

# ---- CORS ------------------------------------------------------------------------------------------------------------
$r = Send-Http OPTIONS "$ApiUrl/api/v1/me" @{ Origin = $WebUrl; 'Access-Control-Request-Method' = 'GET'; 'Access-Control-Request-Headers' = 'authorization,content-type' }
Test-Check 'cors: preflight from the web origin is allowed' ($r.Status -eq 200 -and $r.Headers['access-control-allow-origin'] -eq $WebUrl -and $r.Headers['access-control-allow-headers'] -match 'Authorization') "HTTP $($r.Status), allow-origin=$($r.Headers['access-control-allow-origin'])"

$r = Send-Http OPTIONS "$ApiUrl/api/v1/me" @{ Origin = 'https://evil.example'; 'Access-Control-Request-Method' = 'GET' }
Test-Check 'cors: preflight from a foreign origin is refused' (-not $r.Headers.ContainsKey('access-control-allow-origin')) "HTTP $($r.Status)"

$r = Send-Http GET "$ApiUrl/health" @{ Origin = $WebUrl }
Test-Check 'cors: a simple request from the web origin carries the allow-origin header' ($r.Headers['access-control-allow-origin'] -eq $WebUrl) "allow-origin=$($r.Headers['access-control-allow-origin'])"

# ---- Web -------------------------------------------------------------------------------------------------------------
$landing = Send-Http GET "$WebUrl/"
Test-Check 'web landing page returns 200' ($landing.Status -eq 200 -and $landing.Headers['content-type'] -match 'text/html') "HTTP $($landing.Status), $($landing.Body.Length) bytes"

$r = Send-Http GET "$WebUrl/app"
Test-Check 'web app shell /app returns 200' ($r.Status -eq 200) "HTTP $($r.Status), $($r.Body.Length) bytes"

$r = Send-Http GET "$WebUrl/login"
Test-Check 'web sign-in page /login returns 200' ($r.Status -eq 200) "HTTP $($r.Status)"

# The browser bundle must carry the API origin and the Firebase project (NEXT_PUBLIC_* is inlined at build time).
$scripts = @([regex]::Matches($landing.Body, '(?:src|href)="(/_next/static/[^"]+\.js)"') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
$app = Send-Http GET "$WebUrl/app"
$scripts += @([regex]::Matches($app.Body, '(?:src|href)="(/_next/static/[^"]+\.js)"') | ForEach-Object { $_.Groups[1].Value } | Select-Object -Unique)
$scripts = @($scripts | Select-Object -Unique | Select-Object -First 60)
$foundApi = $false; $foundFirebase = $false; $foundLocalhost = $false
foreach ($path in $scripts) {
    $js = Send-Http GET "$WebUrl$path"
    if ($js.Body.Contains($ApiUrl)) { $foundApi = $true }
    if ($js.Body.Contains($fb.apiKey) -and $js.Body.Contains($fb.projectId)) { $foundFirebase = $true }
    if ($js.Body.Contains('localhost:8000') -or $js.Body.Contains('localhost:8100')) { $foundLocalhost = $true }
    if ($foundApi -and $foundFirebase) { break }
}
Test-Check 'web bundle points at the API URL' $foundApi "$($scripts.Count) script files scanned"
Test-Check 'web bundle carries the Firebase web config' $foundFirebase
Test-Check 'web bundle has no localhost API origin' (-not $foundLocalhost)

# ---- Firebase Hosting (after deploy-hosting.ps1) ------------------------------------------------------------------------
if ($Hosting) {
    $hostUrl = "https://$($script:Project).web.app"
    $r = Send-Http GET "$hostUrl/"
    Test-Check 'hosting: https://omnicult-app.web.app serves the landing page' ($r.Status -eq 200 -and $r.Headers['content-type'] -match 'text/html' -and $r.Body.Length -gt 10000) "HTTP $($r.Status), $($r.Body.Length) bytes"
    $r = Send-Http GET "$hostUrl/app"
    Test-Check 'hosting: /app returns 200 through the Cloud Run rewrite' ($r.Status -eq 200) "HTTP $($r.Status)"
    $r = Send-Http GET "$hostUrl/__/auth/handler"
    Test-Check 'hosting: Firebase Auth handler /__/auth/handler is served' ($r.Status -eq 200) "HTTP $($r.Status)"
    $r = Send-Http OPTIONS "$ApiUrl/api/v1/me" @{ Origin = $hostUrl; 'Access-Control-Request-Method' = 'GET'; 'Access-Control-Request-Headers' = 'authorization' }
    Test-Check 'hosting: API CORS allows the Hosting origin' ($r.Status -eq 200 -and $r.Headers['access-control-allow-origin'] -eq $hostUrl) "HTTP $($r.Status), allow-origin=$($r.Headers['access-control-allow-origin'])"
}

# ---- Signed in -------------------------------------------------------------------------------------------------------
$cleanup = New-Object System.Collections.Generic.List[object]
if (-not $SkipAuth) {
    function New-AnonymousUser {
        $r = Send-Http POST "https://identitytoolkit.googleapis.com/v1/accounts:signUp?key=$($fb.apiKey)" @{ Referer = "$WebUrl/" } '{"returnSecureToken":true}'
        $j = ConvertFrom-JsonSafe $r.Body
        return [pscustomobject]@{ Status = $r.Status; IdToken = $j.idToken; Uid = $j.localId; Error = if ($r.Status -ne 200) { $r.Body } else { '' } }
    }

    $userA = New-AnonymousUser
    Test-Check 'firebase: anonymous sign-in returns an ID token' ($userA.Status -eq 200 -and $userA.IdToken) $(if ($userA.Error) { "HTTP $($userA.Status): $($userA.Error)" } else { 'Identity Toolkit REST, public web API key' })
    if ($userA.IdToken) {
        $cleanup.Add($userA)
        $auth = Get-AuthHeaders $userA.IdToken

        $r = Send-Http GET "$ApiUrl/api/v1/me" $auth
        $me = ConvertFrom-JsonSafe $r.Body
        Test-Check 'api accepts the Firebase ID token: workspace bootstrap (GET /me)' ($r.Status -eq 200 -and $me.is_anonymous -eq $true -and @($me.workspaces).Count -ge 1) "HTTP $($r.Status), workspaces=$(@($me.workspaces).Count), anonymous=$($me.is_anonymous)"

        $r = Send-Http GET "$ApiUrl/api/v1/regions" $auth
        $regions = ConvertFrom-JsonSafe $r.Body
        Test-Check 'reference data: 36 India regions are seeded' ($r.Status -eq 200 -and $regions.total -eq 36) "HTTP $($r.Status), total=$($regions.total)"

        $r = Send-Http POST "$ApiUrl/api/v1/projects/demo" $auth '{}'
        $project = ConvertFrom-JsonSafe $r.Body
        Test-Check 'api: POST /projects/demo creates a demo project' ($r.Status -eq 201 -and $project.id -and $project.mode -eq 'demo') "HTTP $($r.Status), mode=$($project.mode)"

        if ($project.id) {
            $r = Send-Http GET "$ApiUrl/api/v1/projects/$($project.id)/campaigns" $auth
            $campaigns = ConvertFrom-JsonSafe $r.Body
            Test-Check 'api: list campaigns of the demo project' ($r.Status -eq 200 -and $campaigns.total -ge 1) "HTTP $($r.Status), total=$($campaigns.total)"

            $userB = New-AnonymousUser
            if ($userB.IdToken) {
                $cleanup.Add($userB)
                $r = Send-Http GET "$ApiUrl/api/v1/projects/$($project.id)" (Get-AuthHeaders $userB.IdToken)
                Test-Check "authorization: a second user cannot read the first user's project" ($r.Status -in 403, 404) "HTTP $($r.Status)"
            } else {
                Test-Check "authorization: a second user cannot read the first user's project" $false 'second anonymous sign-in failed'
            }
        }

        $r = Send-Http POST "$ApiUrl/api/v1/projects" $auth '{"name":"smoke","brand_name":"smoke"}'
        Test-Check 'authorization: an anonymous user cannot create a live project' ($r.Status -eq 403) "HTTP $($r.Status)"

        if (-not $KeepData -and $project.id) {
            $r = Send-Http DELETE "$ApiUrl/api/v1/projects/$($project.id)" $auth
            Test-Check 'clean-up: demo project archived' ($r.Status -eq 204) "HTTP $($r.Status)"
        }
    }
    if (-not $KeepData) {
        foreach ($u in $cleanup) {
            $r = Send-Http POST "https://identitytoolkit.googleapis.com/v1/accounts:delete?key=$($fb.apiKey)" @{ Referer = "$WebUrl/" } (@{ idToken = $u.IdToken } | ConvertTo-Json -Compress)
            Test-Check 'clean-up: anonymous Firebase user deleted' ($r.Status -eq 200) "HTTP $($r.Status)"
        }
    }
}

# ---- Summary ---------------------------------------------------------------------------------------------------------
$failed = @($results | Where-Object { -not $_.Pass })
Write-Host ''
Write-Host ("{0} checks, {1} passed, {2} failed" -f $results.Count, ($results.Count - $failed.Count), $failed.Count)
if ($failed.Count -gt 0) {
    $failed | ForEach-Object { Write-Host "  FAILED: $($_.Name) $($_.Detail)" }
    exit 1
}
