# ai-delivery

## GCP deployment

The cloud side is intended to run on Cloud Run:

- `ai-delivery-app`: Flask dashboard, Gemini commentary, TikTok listener, frame API
- `ai-delivery-voicevox`: VOICEVOX Engine
- Cloud Storage bucket: generated audio files
- Secret Manager: `API_KEY` and `TIKTOK_UNIQUE_ID`

Terraform lives in `infra/terraform`.

```powershell
$env:API_KEY = "your-gemini-api-key"
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"

.\scripts\deploy-gcp.ps1 `
  -ProjectId "gen-lang-client-0496284195" `
  -Region "asia-northeast1"
```

The deploy script applies Terraform first, adds Secret Manager versions from
environment variables, then deploys the app to Cloud Run from local source using
Cloud Build.

## Streaming flow

The Cloud Run app is request-driven. It does not start the stream loop when the
container boots.

```powershell
$env:CLOUD_APP_URL = "https://your-ai-delivery-app-url"
python -m local_agent.main
```

`local_agent` starts a session, sends captured Minecraft frames to
`/api/frames`, plays returned VOICEVOX audio locally, and stops the session when
the process exits.

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
cloudbuild.googleapis.com
run.googleapis.com
secretmanager.googleapis.com
storage.googleapis.com
```

If `PERMISSION_DENIED` appears while enabling an API, the active account likely
needs Service Usage permissions. Enable the API manually in the console or grant
the account a role such as `Service Usage Admin`.

### Secret not found

`set-gcp-secrets.ps1` is mainly for updating existing Secret Manager values. If
you run it before Terraform creates the secrets, you may see:

```text
Secret ... ai-delivery-api-key not found
```

Preferred flow:

```powershell
.\scripts\deploy-gcp.ps1 -ProjectId "gen-lang-client-0496284195"
```

Then update secret values when needed:

```powershell
$env:API_KEY = "your-gemini-api-key"
$env:TIKTOK_UNIQUE_ID = "@your_tiktok_id"
.\scripts\set-gcp-secrets.ps1 -ProjectId "gen-lang-client-0496284195"
```

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
