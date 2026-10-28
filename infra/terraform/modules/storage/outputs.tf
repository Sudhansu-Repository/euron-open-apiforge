output "bucket_name" {
  description = "Artifacts bucket name (ARTIFACTS_BUCKET)."
  value       = aws_s3_bucket.artifacts.bucket
}

output "bucket_arn" {
  description = "Artifacts bucket ARN, for IAM policies."
  value       = aws_s3_bucket.artifacts.arn
}
