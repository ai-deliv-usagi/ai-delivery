param(
    [string]$ProjectId = "",
    [string]$Region = "asia-northeast1",
    [string]$AppServiceName = "ai-delivery-app",
    [string]$VoicevoxServiceName = "ai-delivery-voicevox",
    [string]$AudioBucketName = "",
    [string]$GeminiModelId = "gemini-2.5-flash-lite",
    [int]$VoicevoxSpeakerId = 63
)

$ErrorActionPreference = "Stop"

$RequiredServices = @(
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com"
)

function Require-Command($Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "$Name is required but was not found in PATH."
    }
}

function Invoke-Checked($Description, $Command, $Arguments) {
    Write-Host $Description
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE."
    }
}

function Enable-GcpServices($ProjectId, $Services) {
    Write-Host "Ensuring required GCP APIs are enabled..."
    foreach ($service in $Services) {
        Invoke-Checked `
            -Description "Enabling $service..." `
            -Command "gcloud" `
            -Arguments @("services", "enable", $service, "--project=$ProjectId")
    }
}

function Wait-ForGcpService($ProjectId, $Service) {
    Write-Host "Waiting for $Service..."
    for ($i = 0; $i -lt 30; $i++) {
        $enabled = gcloud services list `
            --project=$ProjectId `
            --enabled `
            --filter="config.name=$Service" `
            --format="value(config.name)" 2>$null

        if ($enabled -eq $Service) {
            return
        }

        Start-Sleep -Seconds 10
    }

    throw "$Service was not enabled after waiting. Check Service Usage permissions."
}

Require-Command gcloud

$terraformExe = "terraform"
$localTerraform = Join-Path $PSScriptRoot "..\.tools\terraform\terraform.exe"
if (Test-Path $localTerraform) {
    $terraformExe = (Resolve-Path $localTerraform).Path
} elseif (-not (Get-Command terraform -ErrorAction SilentlyContinue)) {
    throw "terraform is required but was not found in PATH or .tools\terraform\terraform.exe."
}

if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    $ProjectId = (gcloud config get-value project 2>$null).Trim()
}

if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    throw "ProjectId is required. Pass -ProjectId or set gcloud config project."
}

if ([string]::IsNullOrWhiteSpace($AudioBucketName)) {
    $AudioBucketName = "$ProjectId-ai-delivery-audio"
}

$terraformDir = (Resolve-Path (Join-Path $PSScriptRoot "..\infra\terraform")).Path
$serviceAccount = "ai-delivery-app@$ProjectId.iam.gserviceaccount.com"

Enable-GcpServices -ProjectId $ProjectId -Services $RequiredServices
foreach ($service in $RequiredServices) {
    Wait-ForGcpService -ProjectId $ProjectId -Service $service
}

Write-Host "Applying Terraform for project $ProjectId in $Region..."
Invoke-Checked `
    -Description "Terraform init" `
    -Command $terraformExe `
    -Arguments @("-chdir=$terraformDir", "init")

Invoke-Checked `
    -Description "Terraform apply" `
    -Command $terraformExe `
    -Arguments @(
        "-chdir=$terraformDir",
        "apply",
        "-auto-approve",
        "-var=project_id=$ProjectId",
        "-var=region=$Region",
        "-var=app_service_name=$AppServiceName",
        "-var=voicevox_service_name=$VoicevoxServiceName",
        "-var=audio_bucket_name=$AudioBucketName",
        "-var=gemini_model_id=$GeminiModelId",
        "-var=voicevox_speaker_id=$VoicevoxSpeakerId"
    )

if ($env:API_KEY) {
    Write-Host "Adding API_KEY secret version..."
    $env:API_KEY | gcloud secrets versions add ai-delivery-api-key --project=$ProjectId --data-file=-
    if ($LASTEXITCODE -ne 0) {
        throw "Adding API_KEY secret version failed."
    }
} else {
    Write-Warning "API_KEY is not set. Secret remains at bootstrap value CHANGE_ME."
}

if ($env:TIKTOK_UNIQUE_ID) {
    Write-Host "Adding TIKTOK_UNIQUE_ID secret version..."
    $env:TIKTOK_UNIQUE_ID | gcloud secrets versions add ai-delivery-tiktok-unique-id --project=$ProjectId --data-file=-
    if ($LASTEXITCODE -ne 0) {
        throw "Adding TIKTOK_UNIQUE_ID secret version failed."
    }
} else {
    Write-Warning "TIKTOK_UNIQUE_ID is not set. Secret remains at bootstrap value CHANGE_ME."
}

$voicevoxUrl = (& $terraformExe "-chdir=$terraformDir" output -raw voicevox_url).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($voicevoxUrl)) {
    throw "Could not read voicevox_url from Terraform output."
}

Invoke-Checked `
    -Description "Deploying app source to Cloud Run..." `
    -Command "gcloud" `
    -Arguments @(
        "run",
        "deploy",
        $AppServiceName,
        "--project=$ProjectId",
        "--region=$Region",
        "--source=.",
        "--service-account=$serviceAccount",
        "--allow-unauthenticated",
        "--min-instances=0",
        "--max-instances=1",
        "--memory=512Mi",
        "--cpu=1",
        "--timeout=3600",
        "--set-env-vars=GEMINI_MODEL_ID=$GeminiModelId,VOICEVOX_URL=$voicevoxUrl,VOICEVOX_SPEAKER_ID=$VoicevoxSpeakerId,AUDIO_BUCKET_NAME=$AudioBucketName",
        "--set-secrets=API_KEY=ai-delivery-api-key:latest,TIKTOK_UNIQUE_ID=ai-delivery-tiktok-unique-id:latest"
    )

$appUrl = (gcloud run services describe $AppServiceName --project=$ProjectId --region=$Region --format="value(status.url)").Trim()
Write-Host "Deployment complete: $appUrl"
