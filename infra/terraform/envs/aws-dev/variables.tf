variable "region" {
  description = "AWS region."
  type        = string
}

variable "environment" {
  description = "Environment tag."
  type        = string
  default     = "dev"
}

variable "extra_tags" {
  description = "Tags added to every resource."
  type        = map(string)
  default     = {}
}

variable "name_prefix" {
  description = "Prefix for every resource name (at most 24 characters); the artifacts bucket name derives from it, so make it globally unique (e.g. \"acme-apiforge-dev\")."
  type        = string
}

variable "hostname" {
  description = "Public host name of the deployment, e.g. apiforge-dev.example.com."
  type        = string
}

variable "certificate_arn" {
  description = "ACM certificate in the same region covering hostname."
  type        = string
}

variable "route53_zone_id" {
  description = "Hosted zone for the hostname alias record. Null: create the CNAME yourself (load_balancer_dns_name output)."
  type        = string
  default     = null
}

variable "image_tag" {
  description = "Image tag to deploy (the git commit or a release)."
  type        = string
}

variable "alarm_email" {
  description = "Alarm notification address."
  type        = string
  default     = null
}

variable "api_extra_environment" {
  description = "Extra api/worker/migrate environment (e.g. DEFAULT_RPM_LIMIT, WORKER_CONCURRENCY, GENERATION_TIMEOUT_S, MAX_BODY_BYTES; see docs/guides/configuration.md). Never secrets."
  type        = map(string)
  default     = {}
}

variable "archive_expiration_days" {
  description = "Days a generated archive under archives/ is kept before S3 deletes it (a new generation of its spec rebuilds it). Uploaded specs never expire."
  type        = number
  default     = 90
}

variable "db_instance_class" {
  description = "RDS instance class."
  type        = string
  default     = "db.t4g.small"
}

variable "cache_node_type" {
  description = "ElastiCache node type."
  type        = string
  default     = "cache.t4g.micro"
}

variable "metrics_allowed_cidrs" {
  description = "Source CIDRs allowed to scrape /metrics through the load balancer. Empty: from anywhere, with the METRICS_TOKEN bearer token (secrets output metrics_token_secret_arn)."
  type        = list(string)
  default     = []
}

variable "worker_metrics_cidrs" {
  description = "In-VPC Prometheus CIDRs allowed to scrape the worker's /metrics on port 9464. Empty: no worker ingress."
  type        = list(string)
  default     = []
}

variable "api_p95_latency_seconds" {
  description = "api p95 response time that raises an alarm."
  type        = number
  default     = 1.5
}
