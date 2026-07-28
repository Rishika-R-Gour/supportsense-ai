locals {
  alarm_actions = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "SupportSense-${var.environment}"
  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "API latency and target errors"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            [
              "AWS/ApplicationELB",
              "TargetResponseTime",
              "LoadBalancer",
              aws_lb.main.arn_suffix,
              "TargetGroup",
              aws_lb_target_group.api.arn_suffix,
              { stat = "p95" },
            ],
            [
              ".",
              "HTTPCode_Target_5XX_Count",
              ".",
              ".",
              ".",
              ".",
              { stat = "Sum" },
            ],
          ]
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "ECS utilization"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            [
              "AWS/ECS",
              "CPUUtilization",
              "ClusterName",
              aws_ecs_cluster.main.name,
              "ServiceName",
              aws_ecs_service.api.name,
            ],
            [".", "MemoryUtilization", ".", ".", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "PostgreSQL"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            [
              "AWS/RDS",
              "CPUUtilization",
              "DBInstanceIdentifier",
              aws_db_instance.postgres.identifier,
            ],
            [".", "DatabaseConnections", ".", "."],
            [".", "FreeStorageSpace", ".", "."],
          ]
        }
      },
      {
        type   = "metric"
        width  = 12
        height = 6
        properties = {
          title  = "Redis"
          region = var.aws_region
          view   = "timeSeries"
          metrics = [
            [
              "AWS/ElastiCache",
              "EngineCPUUtilization",
              "ReplicationGroupId",
              aws_elasticache_replication_group.redis.replication_group_id,
            ],
            [".", "Evictions", ".", "."],
            [".", "CurrConnections", ".", "."],
          ]
        }
      },
    ]
  })
}

resource "aws_cloudwatch_metric_alarm" "api_target_errors" {
  alarm_name          = "supportsense-${var.environment}-api-target-5xx"
  alarm_description   = "API target returned five or more 5xx responses in five minutes."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 2
  threshold           = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "supportsense-${var.environment}-api-p95-latency"
  alarm_description   = "API target p95 latency exceeded two seconds."
  namespace           = "AWS/ApplicationELB"
  metric_name         = "TargetResponseTime"
  extended_statistic  = "p95"
  period              = 60
  evaluation_periods  = 5
  datapoints_to_alarm = 3
  threshold           = 2
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "ecs_cpu" {
  alarm_name          = "supportsense-${var.environment}-ecs-high-cpu"
  alarm_description   = "SupportSense ECS CPU remained above 80 percent."
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 10
  datapoints_to_alarm = 5
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = local.alarm_actions

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
    ServiceName = aws_ecs_service.api.name
  }
}
