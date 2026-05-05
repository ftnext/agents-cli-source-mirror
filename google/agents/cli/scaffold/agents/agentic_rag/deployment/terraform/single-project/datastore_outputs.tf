{% if cookiecutter.data_ingestion and cookiecutter.datastore_type == "agent_platform_vector_search" %}
output "vector_search_collection_id" {
  description = "Vector Search collection ID"
  value       = var.vector_search_collection_id
}

output "pipeline_gcs_bucket_name" {
  description = "Pipeline GCS bucket name"
  value       = google_storage_bucket.data_ingestion_PIPELINE_GCS_ROOT.name
}
{% elif cookiecutter.datastore_type == "agent_platform_search" %}
output "data_store_id" {
  description = "Data store ID"
  value       = data.external.data_store_id.result.data_store_id
}

output "search_engine_id" {
  description = "Search engine ID"
  value       = google_discovery_engine_search_engine.search_engine.engine_id
}

output "docs_bucket_name" {
  description = "Document bucket name"
  value       = google_storage_bucket.docs_bucket.name
}
{% endif %}
