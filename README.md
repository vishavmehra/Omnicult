<div align="center">

# Omnicult

### Regional campaign intelligence for Indian states

Omnicult takes a campaign made for one Indian state and helps a team bring it to another. It learns the region from cited evidence, remakes the creative, tests it with a labelled synthetic panel, decides Go, Fix or Rethink by fixed rules, and keeps the proof.

[What it is](#what-it-is) · [Demo flow](#the-demo-flow) · [Architecture](#architecture) · [Run it locally](#run-it-locally) · [Tests](#tests)

</div>

> **Omnicult is decision support, not a forecast.** The audiences are synthetic, the demo brand is fictional, and the delivery metrics in Live Pulse are sample data. Every claim says where it came from. See [How Omnicult stays honest](#how-omnicult-stays-honest).

## What it is

A brand that makes one film for Maharashtra cannot reuse it in Tamil Nadu by translating the words. The festival, the food, the clothes, the family roles, the script and the claims all change. Today that work is spread across a research agency, a translator, a studio, a media team and an analytics tool, and context is lost at every handoff.

Omnicult keeps it in one workspace, in the order a marketing team works:

| Step | What happens | Workspace |
|---|---|---|
| Learn | The region's languages, festivals, food, customs and sensitivities, each with source, date and confidence | Market Lens |
| Remake | Inspect the original, transcreate it with an English back-translation, apply small changes, lock what must not change | Creative Studio |
| Test | A synthetic panel reacts, and a risk check pins findings to the scene or image region | Audience Lab |
| Decide | Versions are scored by visible rules and each region gets Go, Fix or Rethink with a reason and a next action | Launch Room |
| Prove | One report answers "why did we make this decision?" from the record | Proof Vault |

**Who it is for:** consumer brands entering new states, agencies that make regional variants and must explain each change, and large brands that need approvals and evidence across regions.

## The demo flow

The demo brand is **Aamod**, a fictional festive-sweets brand. Its Diwali film was made in Marathi for Maharashtra, and the brief targets Tamil Nadu, Kerala and West Bengal. Open the app, choose **Try the demo** (anonymous sign-in, no account), and follow the campaign through the workspaces.

1. **Campaign Desk.** Read the brief and Brand Kit. The glossary spells "Aamod" in five scripts and marks the tagline as never translated.
2. **Market Lens.** Open Tamil Nadu. Every claim shows source, date, kind, scope and confidence. The Evidence Meter says how thin or solid the profile is. Two real source disagreements are in the data (West Bengal's Hindi share in the 2011 Census table against Wikipedia, and the day of Dahi Handi in Maharashtra); both values stay visible.
3. **Creative Studio.** X-Ray the film: scenes, keyframes, Marathi transcript with English back-translation, and the Maharashtrian references. Transcreate for Tamil Nadu, apply a Tweak Chip, lock the logo, tin and tagline, and see the Version Tree. The original is never changed.
4. **Audience Lab.** Run a Quick Read on a synthetic Tamil Nadu panel, then a Risk Check. It flags an unsubstantiated superiority claim in the end-card small print, pinned to the scene and the text box.
5. **Launch Room.** Compare original and adapted versions under visible rules. The Readiness Board returns **Fix** until the claim is removed or substantiated.
6. **Live Pulse.** Region dashboard on a labelled sample dataset, plus real comments from the YouTube Data API.
7. **Proof Vault.** Generate the Proof Report: findings, sources, conflicts, creative changes, synthetic audience results, risks, readiness, limitations and run metadata.

The Aamod imagery and voice are AI-generated (Gemini image and speech models) and all on-screen text is rendered in code. The Marathi voice-over was checked by a transcription round trip, not by a native speaker.

## Features by workspace

Omnicult is organised into seven workspaces and a platform layer. Long jobs run in the background with a visible state.

### Campaign Desk

| Feature | What it does |
|---|---|
| Today View | What is running, finished or failed, and which campaigns need attention |
| Campaign Brief | Product, objective, regions, languages, channels, budget, dates and success metric, entered once and read by every workspace |
| Brand Kit | Logo, colours, fonts, product images, tone, protected terms and never-change zones |
| Brand Glossary | Brand spellings by script, preferred translations, pronunciation and do-not-translate terms, checked in code after every adaptation |
| Command Bar | Type what you want done; it runs the same tools the workspaces use |
| Demo Mode | The Aamod campaign on labelled fixtures, kept apart from live records |

### Market Lens

| Feature | What it does |
|---|---|
| Culture Atlas | Cultural signals for a region, each traceable to its source |
| State Profile | Languages, scripts, festivals, food, colours, symbols, humour, family roles, customs and sensitivities for a state, every fact tagged |
| Language Map | Language and script mix by state, from the India reference data and Census 2011 mother-tongue counts |
| Moment Calendar | Public holidays and festivals that matter for timing |
| Market Compare | States side by side on the same evidence |
| Trend Radar | Public-interest trends by region from open data, shown as attention, not demand |
| Category Shelf | How the product category shows up regionally |
| Evidence Meter | Sources, supported claims, freshness, coverage, open conflicts and stale claims, rated weak, partial or solid by named thresholds |

### Creative Studio

| Feature | What it does |
|---|---|
| Creative X-Ray | Image, video (up to 60 s, 50 MB) or audio broken into scenes, keyframes, on-screen text, transcript, claims and cultural observations; transcription verified live |
| Transcreate | Regional copy with a literal English back-translation, the reason for each change, and code checks for script and glossary terms |
| Tone Dials | Formality, code-mixing, urban-rural, playfulness and energy, applied as explicit directives |
| Tweak Chips | Small structured changes, each with target, reason, supporting claims and expected effect |
| Lock and Edit | Locks on logos, products, packshots, taglines and text, enforced by the operation engine, not by the prompt |
| Version Tree | Every operation creates a new version with actor, reason and cost; restore and compare any two |
| Remake: Visuals | A regional key visual from the Gemini image model, with Indic text set in code and locked regions restored pixel for pixel |
| Remake: Sound | A regional voice-over from Gemini speech, confirmed before it runs |
| Remake: Video | A short regional cut with Veo, confirmed and budget-checked before it runs |
| Voice Director | Speak or type a direction; it is transcribed, turned into a typed plan on the same operations as the UI, and applied only after you confirm; verified live |
| Format Fit | Resize and recompose a version for each placement |
| Claim Guard | Checks product claims against what the brand can substantiate, with a human review step |
| Script Check | Checks regional text for the right script and shaping problems |
| Generate studio | Key visual, Indic voice-over, Lyria jingle and Veo video as recorded runs, each sent to Studio as a new version if you choose |

### Audience Lab

| Feature | What it does |
|---|---|
| Quick Read | First reactions, message understanding, confusion and regional concerns from a small synthetic panel |
| Audience Study | A larger bounded panel sampled by state, language, city tier and age band |
| Ask the Panel | Follow-up questions to the same synthetic participants, with their memory kept |
| Live Focus Group | A moderated synthetic discussion you can interject into |
| Buzz Simulator | How talk about a message might spread through a synthetic network |
| Risk Check | Findings pinned to an image region or video moment, with cited ASCI advertising-code clauses and a severity computed by rules |
| Message Check | Whether the intended message survives adaptation |

### Launch Room

| Feature | What it does |
|---|---|
| Compare and Score | Versions scored by fixed rules across clarity, brand fidelity, cultural relevance, sensitivity risk and objective fit |
| Readiness Board | Go, Fix or Rethink per region, with main reason, highest-priority issue, next action, open conflicts and confidence limits |
| Review Links | Expiring, revocable links for sign-off outside the team |
| Region Plan | Which version goes to which region |
| Asset Pack | Everything a region needs, bundled for download |

### Live Pulse

| Feature | What it does |
|---|---|
| Regional Dashboard | Delivery, cost, response, video and outcome by region and version, on a labelled sample dataset, with last-updated time and provisional days marked |
| Alerts | Deterministic rules (CTR drop, cost spike) run daily by Cloud Scheduler |
| Comment Pulse | Themes in real comments fetched through the YouTube Data API |
| Fatigue Watch | Frequency up while response falls, per version and region |
| Weekly Digest | A weekly summary generated by Cloud Scheduler |

### Proof Vault

| Feature | What it does |
|---|---|
| Proof Report | Brief, regions, evidence, conflicts, creative versions, X-Ray and risk findings, transcreation, audience results, readiness, approvals, limitations and run metadata; exports to PDF |
| Evidence Map | Sources, claims, scenes, risks, versions and approvals as one connected map |
| Search | Find any claim, source, scene or decision |
| Run History | Every run with model, prompt version, estimated cost, latency and state |
| Data Health | Stale sources, thin coverage and open conflicts, listed |

### Platform

| Feature | What it does |
|---|---|
| Teams and Roles | Workspaces with owner, editor, reviewer and viewer roles, invites and an audit log, enforced on the server |
| Country Pack: India | All 36 states and union territories with their languages and scripts |
| Usage | Estimated AI spend by workspace and campaign, with run and daily budgets |
| Resumable Runs | Background runs with idempotent start; a restart marks in-flight runs as interrupted and they are safe to retry |
| Model Gateway | One gateway for every model call (see [AI gateway](#ai-gateway)) |

## How Omnicult stays honest

- **Synthetic audiences are labelled synthetic** wherever they appear, on screen and in exports. They are model-written personas sampled by state, language, city tier and age band, never by protected traits. One model voices all of them, so agreement is not confirmation, and nothing here is calibrated against real outcomes.
- **Scores, verdicts and severities are computed by code.** Scoring is `mvp-2`, readiness is `ready-1`, risk severity is `risk-rules-v1`. Models supply observations; they never choose a score, a verdict or a confidence level.
- **Every claim has provenance:** source, date, kind (observed, calculated, synthetic, interpretation or unverified), scope and confidence. When sources disagree, both values stay visible and the conflict lowers dependent confidence until a reviewer resolves it.
- **Confidence is Low, Moderate or High, not a percentage.** Moderate needs two independent observed sources under two years old. High needs native-reviewer confirmation or real campaign results, and the team has no native reviewer, so no claim shows High. Synthetic results never exceed Moderate.
- **Fixtures and samples are labelled.** Aamod is fictional, the Live Pulse delivery metrics are a seeded sample dataset, and saved demonstration results show their original run date.
- **Not claimed:** legal clearance (Risk Check is a screening aid and the ASCI index is a partial set of cited excerpts), sales prediction, or native-quality translation. The Census figures are from 2011. Wikipedia pageviews measure attention, not demand.
- **Failures are shown.** If a model call fails, Omnicult reports it and, where configured, falls back to another Google model and records that in the trace. It never switches to a non-Google provider.

## Architecture

```text
Browser
  |  Firebase Auth ID token (Bearer)
  v
Firebase Hosting --> omnicult-web (Cloud Run, Next.js)
  |  HTTPS
  v
omnicult-api (Cloud Run, FastAPI)
  routes -> services (workspace tenancy, roles, idempotency)
         -> run engine (in process, one instance) -> LangGraph workflows -> agents
                |                       |                      |
                v                       v                      v
          LLM gateway             Culture sources         Media tools
   (Vertex AI Gemini, image,   (Wikidata, pageviews,   (ffmpeg, Pillow,
    speech, Lyria, Veo;        census, holidays,        Noto fonts)
    budgets and metering)      curated, grounding)
         -> deterministic code: confidence, conflicts, Evidence Meter, scoring,
            readiness, risk rules, alerts, report assembly
  |
  +--> Cloud SQL (PostgreSQL)    Cloud Storage (assets, exports)    Secret Manager
Cloud Scheduler --> internal endpoints (daily alerts, weekly digest), OIDC-authenticated
```

- **Web** (`frontend/`): Next.js 16, React 19, TypeScript, Tailwind CSS 4, shadcn/ui on Base UI, TanStack Query and a typed `openapi-fetch` client generated from `contracts/openapi.json`. The browser receives only `NEXT_PUBLIC_*` values and never calls a model.
- **API** (`backend/`): FastAPI on Python 3.13, Pydantic, async SQLAlchemy, Alembic and LangGraph. Every workflow is a graph of named stages; each stage either calls the gateway or runs deterministic code and records a trace.
- **Models write language; code does the rest.** Resolution rules, confidence, conflicts, scoring, readiness, risk severity, script checks, glossary checks, alert rules and report assembly are deterministic. Model output and retrieved text are treated as untrusted and validated against strict schemas.
- **Runs** execute inside the API process, so the API runs as a single instance. A restart marks in-flight runs as interrupted, and starting a run twice with the same `Idempotency-Key` returns the run that already exists.

## Google technologies used

| Product | Use in Omnicult |
|---|---|
| **Gemini on Vertex AI** | Structured text (X-Ray, Transcreate, Tweak Chips, Quick Read, Risk Check, reports), vision on video keyframes, embeddings for search, Google Search grounding for cited research, and transcription of uploads and spoken directions |
| **Gemini image, Gemini speech, Lyria, Veo** | Regional key visuals, Indic voice-over, jingles and short video, always user-confirmed, budget-checked and recorded |
| **Firebase Authentication** | Google sign-in, email and password, and anonymous sessions for the demo; ID tokens verified in the API |
| **Firebase Hosting** | Public entry point in front of the web service |
| **Cloud Run** | `omnicult-api`, `omnicult-web`, and the migration and seed jobs, in `asia-south1` |
| **Cloud SQL for PostgreSQL** | The primary database |
| **Cloud Storage** | Uploaded creatives, derived keyframes, generated media and report exports, served through short-lived signed URLs |
| **Secret Manager** | Database URL and the YouTube API key |
| **Cloud Scheduler** | Daily alert evaluation and the weekly digest, calling OIDC-protected internal endpoints |
| **Cloud Build and Artifact Registry** | Container builds and images for the API and the web app |
| **YouTube Data API** | Real comments for Comment Pulse |

Default models (all configurable through `GEMINI_*` settings; checked against Vertex AI on 17 November 2026):

| Work | Default model |
|---|---|
| Fast text: X-Ray scene structuring, panel interviews | `gemini-3.5-flash-lite` |
| Default text: Transcreate, Tweak Chips, Quick Read, analysis, vision, grounding, transcription | `gemini-3.8-flash` |
| Reasoning: Risk Check (falls back to the default tier if it fails) | `gemini-4-argon` |
| Embeddings, 768 dimensions | `gemini-embedding-2` |
| Image generation (location `global`) | `gemini-3.1-flash-image` |
| Speech | `gemini-3.8-flash-tts` |
| Music | `lyria-002` (`us-central1`) |
| Video | Veo (model id set in configuration) |

## Open data and licences

| Source | Used for | Licence or terms |
|---|---|---|
| Wikidata | Entity resolution, region and language facts | CC0 |
| Wikipedia text | Short cited excerpts as supporting evidence | CC BY-SA 4.0; page URL and title kept as attribution |
| Wikipedia pageviews | Attention trends in the regional and English editions | Wikimedia analytics data; aggregate counts, attributed |
| Census of India 2011, table C-16 | Mother-tongue counts and shares | Published by the Registrar General; only counts are stored, cited to the source |
| python-holidays | Public holidays by state | MIT |
| ASCI Code and guidelines | Cited clauses for Risk Check | Published by ASCI; short exact excerpts with page URL, partial index, not legal advice |
| State tourism and government pages | Short cited excerpts for festivals, food and customs | Each site's own terms |
| Noto Sans fonts | Rendering Indic text in code | SIL Open Font License 1.1 |

Source coverage is uneven by design and reported as such: the curated references cover the four demo states, Wikidata is rate-limited and sparse for some regions, and a region with little evidence is shown as weak.

## AI gateway

All model calls go through one gateway (`backend/app/llm/gateway.py`).

- **Routing.** Each agent names a task class; `routing-v2` maps it to a fast, default or reasoning tier and then to a configured Gemini model. Capability adapters cover embeddings, vision, image generation, speech, grounded research and transcription.
- **Structured output.** Every important call has a Pydantic schema and a `prompt_version` (for example `xray-scenes-v1`, `transcreate-lines-v1`, `tweak-chips-v1`, `quick-read-v1`, `risk-check-v1`). Output is validated, given one repair attempt, and otherwise raised as an error distinct from a provider failure. Invalid output never reaches the database as trusted data.
- **Bounds.** Timeouts, bounded retries for transient errors, and an approved fallback to a lower Google tier that is recorded in the trace.
- **Budgets and metering.** Each request records provider, model, prompt version, tokens, estimated cost and latency in `ai_usage_events`. A call that would pass the per-run budget (default USD 0.50) or the daily budget (default USD 5.00) is refused before it is sent. Costs are estimates from a versioned price table, not invoices.
- **Safety.** Source text is wrapped as untrusted data, and a content-filter block is reported as its own error. Prompts and outputs are not logged.
- **Demo.** Demo workspaces use a fixture provider with no network call.

## Data model

The hierarchy is **workspace** (the tenant) > **brand** (owns the Brand Kit) > **campaign** > versions. Tables fall into these groups, all created by additive Alembic migrations in `backend/migrations/versions/`:

| Area | Tables |
|---|---|
| Identity and tenancy | `users`, `workspaces`, `workspace_members`, `audit_log` |
| Reference data | `languages`, `regions`, `country_packs`, `region_language_profiles`, `regional_moments` |
| Evidence | `claims`, `claim_sources`, `conflicts`, `conflict_resolutions` |
| Creative | `assets`, `creative_assets`, `creative_scenes`, `version_nodes`, `operations`, `locks`, `chips`, `glossary_terms` |
| Audience and launch | `audience_runs`, `audience_participants`, `audience_questions`, `audience_answers`, `audience_risk_findings`, `readiness_verdicts`, `approvals` |
| Pulse and proof | `metric_series`, `proof_reports`, `proof_report_exports` |
| Runs and metering | `agent_runs`, `ai_usage_events`, `embeddings` |

Workspace membership is checked on every request: a non-member gets 404, a member with too little role gets 403. Composite foreign keys keep a child row from pointing at another project. Row Level Security is not used; authorization lives in the API.

## Security and privacy

- Secrets are environment variables or Secret Manager entries. There is no key file: Cloud Run uses its service account through Application Default Credentials. The browser gets only public Firebase identifiers and the API URL.
- Firebase ID tokens are verified in the API (RS256, issuer, audience, expiry). The development auth mode is refused when `APP_ENV=production`, and production start-up also requires Postgres and explicit CORS origins.
- Uploads are typed by magic bytes, size- and duration-limited, probed with ffprobe before storage, and require a rights confirmation for video and audio. Emails and phone numbers are redacted from sidecar text and metadata before any model sees them.
- Synthetic participants are built from aggregate dimensions only; protected traits (religion, caste, health, gender and similar) are refused as sampling dimensions.
- The Cloud Storage bucket has uniform access and enforced public-access prevention; media is served through signed URLs that expire.
- Request models reject unknown fields, errors use one envelope without stack traces, and interactive API docs are off in production.
- Gitleaks runs in CI. The app has not had an independent security audit, and Firebase token revocation is not checked (tokens last one hour).

## Run it locally

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.13), Node.js 22 or newer, and ffmpeg with ffprobe on `PATH` for video and audio. Indic text rendering needs libraqm (with FriBiDi); the Linux image has it, and on a machine without it Latin text renders and Indic text is refused rather than drawn unshaped.

**API**

```bash
cd backend
cp .env.example .env                       # SQLite, AUTH_MODE=dev, no cloud credentials
uv sync
uv run alembic upgrade head
uv run python -m scripts.seed_reference_data
uv run uvicorn app.main:app --reload --port 8000
```

**Web app**

```bash
cd frontend
cp .env.example .env.local                 # API at http://localhost:8000, NEXT_PUBLIC_AUTH_MODE=dev
npm ci
npm run dev                                # http://localhost:3000
```

With `AUTH_MODE=dev` a bearer token `dev-<label>` maps to a stable test user, so no sign-in is needed. Demo workspaces run on fixtures and need no Google credentials. For live runs, set `GOOGLE_CLOUD_PROJECT` and sign in with `gcloud auth application-default login`; live runs spend Vertex AI credit within the budgets below.

Main settings (full list in `backend/.env.example`):

| Variable | Purpose |
|---|---|
| `APP_ENV`, `AUTH_MODE`, `FIREBASE_PROJECT_ID` | Environment and authentication (`dev` or `firebase`) |
| `DATABASE_URL` | SQLite locally, PostgreSQL in production |
| `FRONTEND_ORIGINS` | CORS allow-list |
| `GOOGLE_GENAI_BACKEND`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Vertex AI access (`global` for text and image models) |
| `GEMINI_MODEL_*`, `GEMINI_EMBEDDING_MODEL` | Model ids by tier and capability |
| `AI_RUN_BUDGET_USD`, `AI_DAILY_BUDGET_USD` | Estimated-cost ceilings |
| `ASSET_STORAGE_BACKEND`, `GCS_BUCKET` | `database`, `local` or `gcs` |
| `YOUTUBE_API_KEY` | Comment Pulse |
| `SCHEDULER_SERVICE_ACCOUNT`, `SCHEDULER_AUDIENCE` | Who may call the internal endpoints |
| `WIKIMEDIA_USER_AGENT` | Contact string Wikimedia asks API clients to send |

After changing an API schema, run `uv run python -m scripts.export_openapi` in `backend/` and `npm run gen:api` in `frontend/`.

## Deploy

Deployment scripts for Google Cloud are in `ops/deploy/` (PowerShell). Region is `asia-south1`; Vertex AI image models are reached at `global`.

```powershell
.\ops\deploy\build.ps1 -Target all     # Cloud Build -> Artifact Registry
.\ops\deploy\migrate.ps1               # Cloud Run jobs: alembic upgrade head, then seed reference data
.\ops\deploy\secrets.ps1               # YouTube API key into Secret Manager
.\ops\deploy\deploy-api.ps1 -Public    # Cloud Run, AUTH_MODE=firebase, APP_ENV=production
.\ops\deploy\deploy-web.ps1            # Cloud Run, Firebase config inlined at build time
.\ops\deploy\deploy-hosting.ps1        # Firebase Hosting in front of the web service
.\ops\deploy\scheduler.ps1             # daily alerts and weekly digest jobs
.\ops\deploy\smoke.ps1                 # /health and /ready checks
```

- `omnicult-api` runs with one instance and CPU always allocated, because runs execute in the process. It connects to Cloud SQL through the Cloud Run attachment; the database URL comes from Secret Manager.
- The web app's `NEXT_PUBLIC_*` values are build-time, so a changed API URL needs a web rebuild.
- Google sign-in is enabled once in the Firebase console; email and anonymous sign-in are enabled by script.
- Spend is capped in code by the AI budgets, and a Cloud Billing budget sends alerts.

## Tests

The default backend run is hermetic: SQLite, fixture providers and no paid API call.

```bash
cd backend
uv run pytest -q                                   # unit, API, contract, security, integration
uv run python -m scripts.export_openapi            # then: git diff --exit-code ../contracts/openapi.json
TEST_POSTGRES_URL=postgresql+asyncpg://postgres@127.0.0.1:5432/postgres uv run pytest -q -m postgres tests/postgres

cd ../frontend
npm run typecheck && npm run lint && npm run build
```

The suites cover confidence and conflict rules, scoring, readiness and risk rules, the operation engine and locks, culture adapters on recorded responses, media and Indic text rendering, proof assembly, authorization and tenancy, prompt-injection and secret hygiene, upload limits, and Alembic migrations on PostgreSQL. GitHub Actions runs the backend suite, a PostgreSQL 17 job, the frontend checks and a secret scan. Live Vertex AI checks are opt-in (`scripts/verify_google_models.py --run`).

## Repository layout

```text
backend/     FastAPI service (uv project): app/ (api, services, workflows, agents, analytics, llm, integrations, media), migrations/, scripts/, tests/
frontend/    Next.js app: src/app (routes), src/features (workspaces), src/components, src/lib
contracts/   openapi.json (generated from the API; the web client types come from it)
e2e/         Playwright smoke tests for the web app
ops/         Cloud Build configs, deploy scripts, Firebase and Cloud Storage configuration
```

## Licence and credits

Released under the MIT licence. See [LICENSE](LICENSE).

Cultural data comes from the open sources listed above; Indic text is set in Noto Sans; the interface uses Eczar, Archivo and JetBrains Mono.
