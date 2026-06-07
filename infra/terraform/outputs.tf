output "app_url" {
  description = "Cloud Run URL for the Flask app."
  value       = google_cloud_run_v2_service.app.uri
}

output "voicevox_url" {
  description = "Cloud Run URL for VOICEVOX Engine."
  value       = google_cloud_run_v2_service.voicevox.uri
}

output "audio_bucket_name" {
  description = "Cloud Storage bucket used for generated audio."
  value       = google_storage_bucket.audio.name
}

output "api_key_secret_id" {
  description = "Secret Manager secret ID used for Gemini API key."
  value       = var.api_key_secret_id
}

output "artifact_registry_repository" {
  description = "Artifact Registry repository resource."
  value       = google_artifact_registry_repository.app.name
}
