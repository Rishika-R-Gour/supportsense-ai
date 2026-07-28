output "instance_id" {
  value = aws_instance.demo.id
}

output "public_url" {
  value       = "http://${aws_instance.demo.public_dns}"
  description = "HTTP-only demo URL. The security group limits access to allowed_cidr."
}

output "ssm_session_command" {
  value = "aws ssm start-session --target ${aws_instance.demo.id} --region ${var.aws_region}"
}

output "cost_controls" {
  value = {
    monthly_budget_usd = var.monthly_budget_usd
    auto_stop_hour_utc = var.auto_stop_hour_utc
    cpu_credit_mode    = "standard"
    elastic_ip         = false
  }
}
