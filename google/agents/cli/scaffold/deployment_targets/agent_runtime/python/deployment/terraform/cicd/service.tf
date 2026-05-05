# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Base64-encoded dummy source tarball for initial Agent Runtime creation.
# CI/CD pipelines will update with actual source code after creation.
# The file is pre-encoded to avoid binary corruption when read via Terraform.
locals {
  dummy_source_b64 = trimspace(file("${path.module}/../shared/dummy_source.b64"))
}
{%- if cookiecutter.data_ingestion %}
{%- if cookiecutter.datastore_type == "agent_platform_search" %}

locals {
  data_store_ids = {
    staging = data.external.data_store_id_staging.result.data_store_id
    prod    = data.external.data_store_id_prod.result.data_store_id
  }
}
{%- elif cookiecutter.datastore_type == "agent_platform_vector_search" %}

locals {
  vector_search_collections = {
    for key, project_id in local.deploy_project_ids :
    key => "projects/${project_id}/locations/${var.vector_search_location}/collections/${var.vector_search_collection_id}"
  }
}
{%- endif %}
{%- endif %}

resource "google_vertex_ai_reasoning_engine" "app" {
  for_each = local.deploy_project_ids

  display_name = var.project_name
  description  = "Agent deployed via Terraform"
  region       = var.region
  project      = each.value

  spec {
{%- if cookiecutter.is_adk and not cookiecutter.is_a2a %}
    agent_framework = "google-adk"
{%- else %}
    agent_framework = "custom"
{%- endif %}
    service_account = google_service_account.app_sa[each.key].email

    deployment_spec {
      min_instances         = 1
      max_instances         = 10
      container_concurrency = 9

      resource_limits = {
        cpu    = "4"
        memory = "8Gi"
      }

      env {
        name  = "LOGS_BUCKET_NAME"
        value = google_storage_bucket.logs_data_bucket[each.value].name
      }

      env {
        name  = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
        value = "true"
      }

      env {
        name  = "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"
        value = "true"
      }
{%- if cookiecutter.bq_analytics %}
      env {
        name  = "BQ_ANALYTICS_DATASET_ID"
        value = google_bigquery_dataset.telemetry_dataset[each.key].dataset_id
      }
      env {
        name  = "BQ_ANALYTICS_GCS_BUCKET"
        value = google_storage_bucket.logs_data_bucket[each.value].name
      }
      env {
        name  = "BQ_ANALYTICS_CONNECTION_ID"
        # Format: {location}.{connection_id}
        value = "${var.region}.${google_bigquery_connection.genai_telemetry_connection[each.key].connection_id}"
      }
{%- endif %}
{%- if cookiecutter.data_ingestion %}
{%- if cookiecutter.datastore_type == "agent_platform_search" %}

      env {
        name  = "DATA_STORE_ID"
        value = local.data_store_ids[each.key]
      }

      env {
        name  = "DATA_STORE_REGION"
        value = var.data_store_region
      }
{%- elif cookiecutter.datastore_type == "agent_platform_vector_search" %}

      env {
        name  = "VECTOR_SEARCH_COLLECTION"
        value = local.vector_search_collections[each.key]
      }
{%- endif %}
{%- endif %}
    }

    source_code_spec {
      inline_source {
        source_archive = local.dummy_source_b64
      }

      python_spec {
        entrypoint_module  = "app.agent_runtime_app"
        entrypoint_object  = "agent_runtime"
        requirements_file  = "app/app_utils/.requirements.txt"
        version            = "3.12"
      }
    }
  }

  # This lifecycle block prevents Terraform from overwriting the source code when it's
  # updated by Agent Runtime deployments outside of Terraform (e.g., via CI/CD pipelines)
  lifecycle {
    ignore_changes = [
      spec[0].source_code_spec,
    ]
  }

  # Make dependencies conditional to avoid errors.
  depends_on = [google_project_service.deploy_project_services]
}
