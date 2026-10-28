variable "name_prefix" {
  description = "Prefix for every resource name. The bucket is <name_prefix>-artifacts."
  type        = string
}

variable "kms_key_arn" {
  description = "CMK for SSE-KMS. Null falls back to SSE-S3."
  type        = string
  default     = null
}

variable "enforce_tls" {
  description = "Deny any request not made over TLS. Disable only for an emulator that speaks plain HTTP."
  type        = bool
  default     = true
}

variable "archive_expiration_days" {
  description = "Days a generated archive under archives/ is kept before S3 deletes it. Uploaded specs under specs/ never expire."
  type        = number
  default     = 90
  validation {
    condition     = var.archive_expiration_days >= 1
    error_message = "archive_expiration_days must be at least 1."
  }
}

variable "noncurrent_version_expiration_days" {
  description = "Days an overwritten or deleted object version is kept before S3 removes it."
  type        = number
  default     = 30
  validation {
    condition     = var.noncurrent_version_expiration_days >= 1
    error_message = "noncurrent_version_expiration_days must be at least 1."
  }
}

variable "cors_origins" {
  description = "Browser origins allowed to GET objects with JavaScript (the dashboard URL). Empty = no CORS configuration."
  type        = list(string)
  default     = []
}

variable "force_destroy" {
  description = "Allow `terraform destroy` to delete a non-empty bucket. Never in production."
  type        = bool
  default     = false
}
