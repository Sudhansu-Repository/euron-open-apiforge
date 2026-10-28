# ─────────────────────────────────────────────────────────────────────────────
# Local environment on the Floci AWS emulator.
#
# The modules that build production run here unchanged; only the provider endpoints
# differ. `make up` applies this automatically (the compose `terraform` one-shot)
# before migrate, api and worker start, so the local stack stores uploaded specs and
# generated archives in the artifacts bucket (apiforge-local-artifacts, SSE-KMS with
# alias/apiforge-local) exactly as AWS does, and the Secrets Manager secret exists as it
# would there. By hand, against a running emulator:
#
#   terraform -chdir=infra/terraform/envs/local-floci init
#   terraform -chdir=infra/terraform/envs/local-floci apply -var endpoint=http://localhost:4666
#
# Postgres and Redis are plain Compose containers locally (the emulator does not back
# RDS or ElastiCache); the database and cache modules are exercised by aws-dev and
# aws-prod, which must validate cleanly.
# ─────────────────────────────────────────────────────────────────────────────

module "kms" {
  source                  = "../../modules/kms"
  name_prefix             = var.name_prefix
  deletion_window_in_days = 7
}

module "storage" {
  source                  = "../../modules/storage"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  enforce_tls             = false # the emulator speaks plain HTTP
  force_destroy           = true
  cors_origins            = var.cors_origins
  archive_expiration_days = var.archive_expiration_days
}

# Generated secrets are an AWS-deployment concern; locally compose reads
# deploy/compose/.env (make env). Created here anyway so the module is exercised.
module "secrets" {
  source                  = "../../modules/secrets"
  name_prefix             = var.name_prefix
  kms_key_arn             = module.kms.key_arn
  recovery_window_in_days = 0
}
