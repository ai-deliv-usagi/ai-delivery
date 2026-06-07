locals {
  required_services = toset([
    "artifactregistry.googleapis.com",
    "aiplatform.googleapis.com",
    "cloudbuild.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])

  app_env = {
    GEMINI_MODEL_ID     = var.gemini_model_id
    GCP_PROJECT_ID      = var.project_id
    VERTEX_AI_LOCATION  = var.vertex_ai_location
    VOICEVOX_SPEAKER_ID = tostring(var.voicevox_speaker_id)
    VOICEVOX_URL        = google_cloud_run_v2_service.voicevox.uri
    AUDIO_BUCKET_NAME   = google_storage_bucket.audio.name
  }
}

removed {
  from = google_secret_manager_secret.api_key

  lifecycle {
    destroy = false
  }
}

removed {
  from = google_secret_manager_secret_version.api_key_bootstrap

  lifecycle {
    destroy = false
  }
}

removed {
  from = google_secret_manager_secret.tiktok_unique_id

  lifecycle {
    destroy = false
  }
}

removed {
  from = google_secret_manager_secret_version.tiktok_unique_id_bootstrap

  lifecycle {
    destroy = false
  }
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "app" {
  location      = var.region
  repository_id = var.artifact_registry_repository
  description   = "Container images for ai-delivery."
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "audio" {
  name                        = var.audio_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  lifecycle_rule {
    condition {
      age = 1
    }
    action {
      type = "Delete"
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_service_account" "app" {
  account_id   = "ai-delivery-app"
  display_name = "AI Delivery Cloud Run app"

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "app_vertex_ai_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_storage_bucket_iam_member" "app_audio_admin" {
  bucket = google_storage_bucket.audio.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_cloud_run_v2_service" "voicevox" {
  name     = var.voicevox_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.voicevox_image

      ports {
        container_port = 50021
      }

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_cloud_run_v2_service" "app" {
  name     = var.app_service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.app.email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    containers {
      image = var.app_image

      ports {
        container_port = 8080
      }

      dynamic "env" {
        for_each = local.app_env
        content {
          name  = env.key
          value = env.value
        }
      }

      resources {
        cpu_idle = false

        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.app_vertex_ai_user,
    google_storage_bucket_iam_member.app_audio_admin,
    google_cloud_run_v2_service.voicevox,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "app_public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.app.location
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "voicevox_public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.voicevox.location
  name     = google_cloud_run_v2_service.voicevox.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
