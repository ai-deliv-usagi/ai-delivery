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
