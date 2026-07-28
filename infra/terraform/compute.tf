resource "aws_ecr_repository" "api" {
  name                 = "supportsense-api"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "supportsense-frontend"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/ecs/supportsense-${var.environment}"
  retention_in_days = var.environment == "production" ? 90 : 14
}

resource "aws_ecs_cluster" "main" {
  name = "supportsense-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_iam_role" "execution" {
  name = "supportsense-${var.environment}-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "secrets" {
  role = aws_iam_role.execution.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "kms:Decrypt"]
      Resource = [aws_secretsmanager_secret.application.arn]
    }]
  })
}

resource "aws_iam_role" "task" {
  name = "supportsense-${var.environment}-task"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "uploads" {
  role = aws_iam_role.task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
      Resource = ["${aws_s3_bucket.uploads.arn}/*"]
    }]
  })
}

resource "aws_lb" "main" {
  name               = "supportsense-${var.environment}"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = aws_subnet.public[*].id
}

resource "aws_lb_target_group" "api" {
  name        = "supportsense-${var.environment}"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health/ready"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }
}

resource "aws_lb_target_group" "frontend" {
  name        = "supportsense-ui-${var.environment}"
  port        = 8501
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/_stcore/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
    timeout             = 5
    matcher             = "200"
  }

  stickiness {
    type            = "lb_cookie"
    cookie_duration = 86400
    enabled         = true
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend.arn
  }
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = [
        "/api/*",
        "/health/*",
        "/docs*",
        "/openapi.json",
      ]
    }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "supportsense-${var.environment}"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 2048
  memory                   = 4096
  execution_role_arn       = aws_iam_role.execution.arn
  task_role_arn            = aws_iam_role.task.arn

  container_definitions = jsonencode([
    {
      name         = "api"
      image        = "${aws_ecr_repository.api.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 8000, protocol = "tcp" }]
      environment = [
        { name = "SUPPORTSENSE_ENV", value = "production" },
        { name = "SUPPORTSENSE_ROLLOUT_STAGE", value = "offline" },
        { name = "SUPPORTSENSE_TOOL_BACKEND", value = "http" },
        { name = "SUPPORTSENSE_TRACES_SAMPLE_RATE", value = "0.1" },
        { name = "LANGFUSE_BASE_URL", value = "https://us.cloud.langfuse.com" },
        { name = "UPLOAD_BUCKET", value = aws_s3_bucket.uploads.id },
        {
          name  = "REDIS_URL"
          value = "rediss://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379/0"
        }
      ]
      secrets = [
        {
          name      = "DATABASE_URL"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:DATABASE_URL::"
        },
        {
          name      = "SUPPORTSENSE_JWT_PUBLIC_KEY"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:JWT_PUBLIC_KEY::"
        },
        {
          name      = "SUPPORTSENSE_JWT_ISSUER"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:JWT_ISSUER::"
        },
        {
          name      = "SUPPORTSENSE_JWT_AUDIENCE"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:JWT_AUDIENCE::"
        },
        {
          name      = "SUPPORTSENSE_TOOL_API_URL"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:TOOL_API_URL::"
        },
        {
          name      = "SUPPORTSENSE_TOOL_API_TOKEN"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:TOOL_API_TOKEN::"
        },
        {
          name      = "CHROMA_URL"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:CHROMA_URL::"
        },
        {
          name      = "SENTRY_DSN"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:SENTRY_DSN::"
        },
        {
          name      = "LANGFUSE_PUBLIC_KEY"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:LANGFUSE_PUBLIC_KEY::"
        },
        {
          name      = "LANGFUSE_SECRET_KEY"
          valueFrom = "${aws_secretsmanager_secret.application.arn}:LANGFUSE_SECRET_KEY::"
        }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "api"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health/ready')\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    },
    {
      name         = "frontend"
      image        = "${aws_ecr_repository.frontend.repository_url}:${var.image_tag}"
      essential    = true
      portMappings = [{ containerPort = 8501, protocol = "tcp" }]
      environment = [
        { name = "SUPPORTSENSE_API_URL", value = "http://127.0.0.1:8000" }
      ]
      dependsOn = [
        { containerName = "api", condition = "HEALTHY" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.api.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "frontend"
        }
      }
      healthCheck = {
        command     = ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')\""]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 30
      }
    }
  ])
}

resource "aws_ecs_service" "api" {
  name            = "supportsense-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = var.desired_count
  launch_type     = "FARGATE"

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.app.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 8501
  }

  depends_on = [
    aws_lb_listener.https,
    aws_lb_listener_rule.api,
  ]
}

resource "aws_appautoscaling_target" "api" {
  max_capacity       = 10
  min_capacity       = var.desired_count
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

resource "aws_appautoscaling_policy" "cpu" {
  name               = "supportsense-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.api.resource_id
  scalable_dimension = aws_appautoscaling_target.api.scalable_dimension
  service_namespace  = aws_appautoscaling_target.api.service_namespace

  target_tracking_scaling_policy_configuration {
    target_value = 60
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
  }
}
