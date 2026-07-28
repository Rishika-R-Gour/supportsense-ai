data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

data "aws_ami" "amazon_linux_2023" {
  most_recent = true
  owners      = ["137112412989"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }

  filter {
    name   = "root-device-type"
    values = ["ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_security_group" "demo" {
  name_prefix = "supportsense-free-plan-"
  description = "HTTP access limited to the operator; administration uses SSM."
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SupportSense staging UI and API"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "instance" {
  name_prefix = "supportsense-free-plan-"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ec2.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "instance" {
  name_prefix = "supportsense-free-plan-"
  role        = aws_iam_role.instance.name
}

resource "aws_instance" "demo" {
  ami                         = data.aws_ami.amazon_linux_2023.id
  instance_type               = var.instance_type
  subnet_id                   = sort(data.aws_subnets.default.ids)[0]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  vpc_security_group_ids      = [aws_security_group.demo.id]

  instance_initiated_shutdown_behavior = "stop"
  user_data_replace_on_change          = false
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    auto_stop_hour_utc = var.auto_stop_hour_utc
    buildx_checksum    = "d41ece72044243b4f58b343441ae37446d9c29a7d6b5e11c61847bbcf8f7dfda"
    buildx_version     = "v0.35.0"
    compose_checksum   = "f9ebc6ebdb19d769b793c245a736caaeb198c62587f13b25c660c13b4987f959"
    compose_version    = "v5.3.1"
    git_ref            = var.git_ref
    repository_url     = var.repository_url
  })

  credit_specification {
    cpu_credits = "standard"
  }

  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"
  }

  root_block_device {
    encrypted             = true
    volume_size           = 20
    volume_type           = "gp3"
    delete_on_termination = true
  }

  tags = {
    Name = "supportsense-free-plan-staging"
  }
}

resource "aws_budgets_budget" "monthly" {
  name         = "supportsense-free-plan-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}
