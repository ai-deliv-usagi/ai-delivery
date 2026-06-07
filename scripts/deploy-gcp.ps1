param(
    [string]$ProjectId = "",
    [string]$Region = "asia-northeast1",
    [string]$AppServiceName = "ai-delivery-app",
    [string]$VoicevoxServiceName = "ai-delivery-voicevox",
    [string]$AudioBucketName = "",
    [string]$GeminiModelId = "gemini-2.5-flash-lite",
    [string]$TiktokUniqueId = "",
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

function Ensure-Secret($ProjectId, $SecretId) {
    gcloud secrets describe $SecretId --project=$ProjectId *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Creating Secret Manager secret: $SecretId"
    gcloud secrets create $SecretId --project=$ProjectId --replication-policy=automatic
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Secret Manager secret: $SecretId"
    }
}

function Test-SecretHasVersion($ProjectId, $SecretId) {
    $versions = gcloud secrets versions list $SecretId `
        --project=$ProjectId `
        --filter="state:ENABLED" `
        --format="value(name)" 2>$null

    return -not [string]::IsNullOrWhiteSpace($versions)
}

function Add-SecretVersion($ProjectId, $SecretId, $Value) {
    $cleanValue = $Value.Trim().TrimStart([char]0xFEFF)
    $tempFile = [System.IO.Path]::GetTempFileName()
    try {
        [System.IO.File]::WriteAllText($tempFile, $cleanValue, [System.Text.UTF8Encoding]::new($false))
        gcloud secrets versions add $SecretId --project=$ProjectId --data-file=$tempFile
        if ($LASTEXITCODE -ne 0) {
            throw "Adding secret version failed for $SecretId."
        }
    } finally {
        Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
    }
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

if (-not [string]::IsNullOrWhiteSpace($TiktokUniqueId)) {
    Write-Warning "TiktokUniqueId is now used by local_agent only. Set TIKTOK_UNIQUE_ID in local .env instead."
}

$terraformDir = (Resolve-Path (Join-Path $PSScriptRoot "..\infra\terraform")).Path
$serviceAccount = "ai-delivery-app@$ProjectId.iam.gserviceaccount.com"

Enable-GcpServices -ProjectId $ProjectId -Services $RequiredServices
foreach ($service in $RequiredServices) {
    Wait-ForGcpService -ProjectId $ProjectId -Service $service
}

Ensure-Secret -ProjectId $ProjectId -SecretId "ai-delivery-api-key"
if ($env:API_KEY) {
    Write-Host "Adding API_KEY secret version..."
    Add-SecretVersion -ProjectId $ProjectId -SecretId "ai-delivery-api-key" -Value $env:API_KEY
} elseif (-not (Test-SecretHasVersion -ProjectId $ProjectId -SecretId "ai-delivery-api-key")) {
    throw "API_KEY is not set and ai-delivery-api-key has no enabled versions. Set API_KEY or add a Secret Manager version manually."
} else {
    Write-Host "Using existing API_KEY secret version."
}

Write-Host "Applying Terraform for project $ProjectId in $Region..."
$terraformApplyArgs = @(
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

Invoke-Checked `
    -Description "Terraform init" `
    -Command $terraformExe `
    -Arguments @("-chdir=$terraformDir", "init")

Invoke-Checked `
    -Description "Terraform apply" `
    -Command $terraformExe `
    -Arguments $terraformApplyArgs

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
        "--set-secrets=API_KEY=ai-delivery-api-key:latest"
    )

$appUrl = (gcloud run services describe $AppServiceName --project=$ProjectId --region=$Region --format="value(status.url)").Trim()
Write-Host "Deployment complete: $appUrl"
