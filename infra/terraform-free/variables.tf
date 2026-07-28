variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "instance_type" {
  type        = string
  default     = "t3.small"
  description = "Two GiB is the practical minimum for the six-container demo stack."

  validation {
    condition     = var.instance_type == "t3.small"
    error_message = "Use the x86_64 Free Plan-eligible t3.small instance type."
  }
}

variable "allowed_cidr" {
  type        = string
  description = "Your public IPv4 address in CIDR form, for example 203.0.113.10/32."

  validation {
    condition     = can(cidrnetmask(var.allowed_cidr)) && !strcontains(var.allowed_cidr, ":")
    error_message = "allowed_cidr must be a valid IPv4 CIDR."
  }
}

variable "budget_email" {
  type        = string
  description = "Email address that receives AWS Budget alerts."

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_email))
    error_message = "budget_email must be a valid email address."
  }
}

variable "monthly_budget_usd" {
  type        = number
  default     = 10
  description = "Account-level monthly budget guardrail for the credits-limited deployment."

  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 15
    error_message = "monthly_budget_usd must be between 1 and 15."
  }
}

variable "repository_url" {
  type    = string
  default = "https://github.com/Rishika-R-Gour/supportsense-ai.git"
}

variable "git_ref" {
  type    = string
  default = "main"
}

variable "auto_stop_hour_utc" {
  type        = number
  default     = 2
  description = "UTC hour when the instance shuts itself down every day."

  validation {
    condition     = var.auto_stop_hour_utc >= 0 && var.auto_stop_hour_utc <= 23
    error_message = "auto_stop_hour_utc must be from 0 through 23."
  }
}
