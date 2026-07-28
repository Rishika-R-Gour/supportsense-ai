output "api_url" {
  value = "https://${aws_lb.main.dns_name}"
}

output "ecr_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "frontend_ecr_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "application_secret_arn" {
  value = aws_secretsmanager_secret.application.arn
}

output "upload_bucket" {
  value = aws_s3_bucket.uploads.id
}

output "postgres_endpoint" {
  value     = aws_db_instance.postgres.address
  sensitive = true
}
