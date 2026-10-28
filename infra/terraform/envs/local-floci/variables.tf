variable "endpoint" {
  description = "Emulator endpoint. http://floci:4566 inside compose, http://localhost:4666 from the host."
  type        = string
  default     = "http://localhost:4666"
}

variable "name_prefix" {
  description = "Must match ARTIFACTS_BUCKET (<name_prefix>-artifacts) in deploy/compose/compose.floci.yaml."
  type        = string
  default     = "apiforge-local"
}

variable "cors_origins" {
  description = "Dashboard origins allowed to fetch artifact objects with JavaScript (none needed: downloads go through the API)."
  type        = list(string)
  default     = ["http://localhost:4610", "http://127.0.0.1:4610"]
}

variable "archive_expiration_days" {
  description = "Days a generated archive under archives/ is kept locally."
  type        = number
  default     = 90
}
