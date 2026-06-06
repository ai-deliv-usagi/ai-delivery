param(
    [string]$ProjectId = ""
)

$ErrorActionPreference = "Stop"

function Ensure-Secret($ProjectId, $SecretId) {
    gcloud secrets describe $SecretId --project=$ProjectId *> $null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    Write-Host "Creating Secret Manager secret: $SecretId"
    gcloud secrets create $SecretId --project=$ProjectId --replication-policy=automatic
}

if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    $ProjectId = (gcloud config get-value project 2>$null).Trim()
}

if ([string]::IsNullOrWhiteSpace($ProjectId)) {
    throw "ProjectId is required. Pass -ProjectId or set gcloud config project."
}

if (-not $env:API_KEY) {
    throw "Set API_KEY in the current shell before running this script."
}

Ensure-Secret -ProjectId $ProjectId -SecretId "ai-delivery-api-key"

$env:API_KEY | gcloud secrets versions add ai-delivery-api-key --project=$ProjectId --data-file=-

Write-Host "API_KEY secret version added."
