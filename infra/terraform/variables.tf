variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run and Artifact Registry."
  type        = string
  default     = "asia-northeast1"
}

variable "app_service_name" {
  description = "Cloud Run service name for the Flask app."
  type        = string
  default     = "ai-delivery-app"
}

variable "voicevox_service_name" {
  description = "Cloud Run service name for VOICEVOX Engine."
  type        = string
  default     = "ai-delivery-voicevox"
}

variable "artifact_registry_repository" {
  description = "Artifact Registry repository name."
  type        = string
  default     = "ai-delivery"
}

variable "audio_bucket_name" {
  description = "Globally unique Cloud Storage bucket name for generated audio."
  type        = string
}

variable "app_image" {
  description = "Initial app container image. Deploy script updates Cloud Run from source after Terraform creates infra."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "api_key_secret_id" {
  description = "Secret Manager secret ID that stores the Gemini API key. Secret versions are managed outside Terraform."
  type        = string
  default     = "ai-delivery-api-key"
}

variable "voicevox_image" {
  description = "VOICEVOX Engine container image."
  type        = string
  default     = "voicevox/voicevox_engine:cpu-ubuntu20.04-latest"
}

variable "gemini_model_id" {
  description = "Gemini model ID used by the application."
  type        = string
  default     = "gemini-2.5-flash-lite"
}

variable "tiktok_unique_id" {
  description = "TikTok Live unique ID, for example @your_tiktok_id. This is not treated as a secret."
  type        = string
}

variable "voicevox_speaker_id" {
  description = "VOICEVOX speaker ID."
  type        = number
  default     = 63
}

variable "allow_unauthenticated" {
  description = "Whether to allow unauthenticated access to Cloud Run services."
  type        = bool
  default     = true
}
