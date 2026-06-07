# ai-delivery

## GCP deployment

The cloud side is intended to run on Cloud Run:

- `ai-delivery-app`: Flask dashboard, Gemini commentary, local event API, frame API
- `ai-delivery-voicevox`: VOICEVOX Engine
- Cloud Storage bucket: generated audio files
- Vertex AI Gemini via the Cloud Run service account

Terraform lives in `infra/terraform`.

```powershell
.\scripts\deploy-gcp.ps1 `
  -ProjectId "gen-lang-client-0496284195" `
  -Region "asia-northeast1"
```

The deploy script applies Terraform first, then deploys the app to Cloud Run
from local source using Cloud Build. Gemini uses Vertex AI authentication through
the Cloud Run service account, so no Gemini API key or Secret Manager value is
needed.

## Streaming flow

The Cloud Run app is request-driven. It does not start the stream loop when the
container boots. During an active session, it runs a lightweight background
event loop so gift queues, jack expiry, and dashboard timers can advance without
waiting for `/api/frames` or `/api/status`.

Session state is persisted to Cloud Storage under `state/stream-session.json`.
If the Cloud Run app instance is restarted during a stream, the next request can
restore the active session flag, current jack mode, jack expiry, queued gifts,
and pending viewer context.

Create a local virtual environment for `local_agent`:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-local.txt
```

```powershell
$env:CLOUD_APP_URL = "https://your-ai-delivery-app-url"
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"
python -m local_agent.main
```

`local_agent` starts a session, sends captured Minecraft frames to
`/api/frames`, sends TikTok Live comments/gifts/follows to `/api/events`, plays
returned VOICEVOX audio locally, and stops the session when the process exits.

Useful checks:

```powershell
curl -X POST "$env:CLOUD_APP_URL/api/session/start"
curl "$env:CLOUD_APP_URL/api/status"
curl -X POST "$env:CLOUD_APP_URL/api/session/stop"
```

VOICEVOX runs as a separate Cloud Run service. The app service calls
`VOICEVOX_URL/audio_query` and `VOICEVOX_URL/synthesis`, returns the generated
WAV bytes as base64 in the `/api/frames` response, and the local agent plays the
audio on the local PC.

## GCP troubleshooting

### Terraform fails with `invalid_grant`

`gcloud auth login` and Terraform's Application Default Credentials are separate.
If Terraform shows an OAuth error such as:

```text
oauth2: "invalid_grant" "Token has been expired or revoked."
```

refresh ADC:

```powershell
gcloud auth application-default login
gcloud auth application-default set-quota-project gen-lang-client-0496284195
gcloud auth application-default print-access-token
```

Then retry:

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
.\scripts\deploy-gcp.ps1 -ProjectId "gen-lang-client-0496284195"
```

### API enablement errors

The deploy script enables required APIs before Terraform runs:

```text
artifactregistry.googleapis.com
aiplatform.googleapis.com
cloudbuild.googleapis.com
run.googleapis.com
storage.googleapis.com
```

If `PERMISSION_DENIED` appears while enabling an API, the active account likely
needs Service Usage permissions. Enable the API manually in the console or grant
the account a role such as `Service Usage Admin`.

`TIKTOK_UNIQUE_ID` is not stored in Secret Manager and is not deployed to Cloud
Run. Set it in the local environment or local `.env` before running
`python -m local_agent.main`.

### PowerShell and Terraform `-chdir`

Pass Terraform arguments carefully in PowerShell. The deploy script resolves the
Terraform directory and passes `-chdir` as an expanded argument. If you run
Terraform manually, this form is safe:

```powershell
.\.tools\terraform\terraform.exe -chdir=infra\terraform plan
```

An error like this means the path was passed literally instead of expanded:

```text
Error handling -chdir option: chdir $terraformDir: The system cannot find the file specified.
```
