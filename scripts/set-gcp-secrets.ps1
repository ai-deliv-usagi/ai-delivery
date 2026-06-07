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

Add-SecretVersion -ProjectId $ProjectId -SecretId "ai-delivery-api-key" -Value $env:API_KEY

Write-Host "API_KEY secret version added."
