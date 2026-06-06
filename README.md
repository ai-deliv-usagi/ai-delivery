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
