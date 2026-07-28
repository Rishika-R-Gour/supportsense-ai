variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "staging"

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production"
  }
}

variable "image_tag" {
  type        = string
  description = "Immutable container tag, normally the Git commit SHA."
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate ARN for the public HTTPS listener."
}

variable "desired_count" {
  type    = number
  default = 2
}

variable "database_instance_class" {
  type    = string
  default = "db.t4g.micro"
}

variable "alarm_topic_arn" {
  type        = string
  default     = null
  nullable    = true
  description = "Optional SNS topic ARN for CloudWatch alarm notifications."
}
