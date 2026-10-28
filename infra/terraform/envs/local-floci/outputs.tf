output "artifacts_bucket" {
  description = "ARTIFACTS_BUCKET for the local stack (specs/ and archives/)."
  value       = module.storage.bucket_name
}

output "kms_key_alias" {
  description = "Alias of the key that encrypts the artifacts bucket and the secret."
  value       = module.kms.alias_name
}

output "app_secret_arn" {
  description = "The emulated Secrets Manager secret (SESSION_SECRET, API_KEY_PEPPER)."
  value       = module.secrets.secret_arn
}
