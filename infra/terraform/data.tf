resource "aws_db_subnet_group" "main" {
  name       = "supportsense-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "postgres" {
  identifier                   = "supportsense-${var.environment}"
  engine                       = "postgres"
  engine_version               = "16"
  instance_class               = var.database_instance_class
  allocated_storage            = 20
  max_allocated_storage        = 100
  storage_type                 = "gp3"
  storage_encrypted            = true
  db_name                      = "supportsense"
  username                     = "supportsense"
  manage_master_user_password  = true
  db_subnet_group_name         = aws_db_subnet_group.main.name
  vpc_security_group_ids       = [aws_security_group.data.id]
  backup_retention_period      = var.environment == "production" ? 14 : 3
  deletion_protection          = var.environment == "production"
  skip_final_snapshot          = var.environment != "production"
  performance_insights_enabled = true
  multi_az                     = var.environment == "production"
  enabled_cloudwatch_logs_exports = [
    "postgresql",
    "upgrade",
  ]
  copy_tags_to_snapshot      = true
  auto_minor_version_upgrade = true
  apply_immediately          = false
}

resource "aws_elasticache_subnet_group" "main" {
  name       = "supportsense-${var.environment}"
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id       = "supportsense-${var.environment}"
  description                = "SupportSense queue, cache, and rate-limit store"
  engine                     = "redis"
  node_type                  = "cache.t4g.micro"
  num_cache_clusters         = var.environment == "production" ? 2 : 1
  automatic_failover_enabled = var.environment == "production"
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.data.id]
  snapshot_retention_limit   = var.environment == "production" ? 7 : 1
}

resource "aws_s3_bucket" "uploads" {
  bucket_prefix = "supportsense-${var.environment}-uploads-"
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket                  = aws_s3_bucket.uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id
  rule {
    id     = "expire-raw-uploads"
    status = "Enabled"
    filter {}
    expiration {
      days = 90
    }
  }
}

resource "aws_secretsmanager_secret" "application" {
  name                    = "supportsense/${var.environment}/application"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
}
