output "url" {
  description = "Public URL: the dashboard; the REST API under /api/v1, its docs at /docs."
  value       = module.service.url
}

output "load_balancer_dns_name" {
  description = "CNAME target when the zone is not in Route53."
  value       = module.service.alb_dns_name
}

output "cluster_name" {
  description = "ECS cluster."
  value       = module.service.cluster_name
}

output "services" {
  description = "ECS service names."
  value       = module.service.service_names
}

output "ecr_repositories" {
  description = "Image repositories."
  value       = module.ecr.repository_urls
}

output "run_task" {
  description = "Parameters for one-off tasks (migrate, seed-demo, create-owner)."
  value       = module.service.run_task
}

output "artifacts_bucket" {
  description = "Artifacts bucket for specs and generated archives (ARTIFACTS_BUCKET)."
  value       = module.storage.bucket_name
}

output "metrics_token_secret_arn" {
  description = "Secrets Manager secret holding METRICS_TOKEN, the bearer token for scraping /metrics."
  value       = module.secrets.metrics_token_secret_arn
}

output "kms_key_alias" {
  description = "Alias of the key that encrypts data at rest (artifacts, database, cache, secrets, logs)."
  value       = module.kms.alias_name
}

output "dashboard_name" {
  description = "CloudWatch dashboard."
  value       = module.observability.dashboard_name
}

output "image_tag" {
  description = "The image tag the services run (aws-deploy.sh holds them on it while the next release migrates)."
  value       = var.image_tag
}
