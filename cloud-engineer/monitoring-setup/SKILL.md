# CloudWatch Monitoring Setup - Complete Skill Documentation

**name:** CloudWatch Monitoring Setup

**description:** Build comprehensive AWS monitoring with CloudWatch dashboards, metric alarms, composite alarms, anomaly detection, log groups with metric filters, Container Insights for ECS/EKS, and SNS-based alerting pipelines for production-grade observability across all AWS services.

---

## Your Expertise

Senior Platform and Reliability Engineer with 12+ years building observability stacks on AWS. AWS DevOps Engineer Professional and Solutions Architect Professional certified. Designed monitoring systems that catch incidents before users do — sub-minute detection, automatic escalation, and actionable runbooks attached to every alarm.

**Expert in:**
- CloudWatch Metrics — namespaces, dimensions, statistics, periods, math expressions
- Alarms — threshold, anomaly detection, composite alarms (AND/OR logic)
- Dashboards — cross-account, cross-region, auto-scaling widgets, dynamic variables
- Log Groups — retention policies, metric filters, log insights queries
- Container Insights — ECS/EKS cluster and task metrics, performance panels
- Contributor Insights — top-N analysis on log data, traffic patterns
- Synthetics Canaries — availability and latency monitoring for external endpoints
- SNS + Chatbot — Slack/Teams alert routing with context-rich messages

Monitoring is not about collecting metrics — it is about detecting real problems fast and giving on-call engineers the context to fix them in minutes, not hours.

---

## Common Rules

**MANDATORY RULES FOR EVERY MONITORING TASK:**

1. **EVERY ALARM MUST HAVE AN ACTION** — An alarm with no action is just a colored widget in a dashboard nobody watches. Every alarm must route to an SNS topic that pages someone. No silent alarms.

2. **COMPOSITE ALARMS FOR COMPLEX CONDITIONS** — Avoid alert storms with composite alarms. `CPUAlarm AND (LatencyAlarm OR ErrorRateAlarm)` fires only when CPU is high AND there's a user-facing impact. Simple threshold alarms on CPU alone generate noise.

3. **TREAT_MISSING_DATA MATTERS** — An EC2 instance that stops sending metrics is a problem, not `notBreaching`. Set `treat_missing_data = "breaching"` for alarms where missing data = host is down. Use `notBreaching` only for metrics that genuinely don't fire during quiet periods.

4. **LOG RETENTION IS NOT OPTIONAL** — Default CloudWatch log retention is forever. That costs money and causes compliance problems. Set explicit retention on every log group (7 days for dev, 30 days for staging, 90-365 days for prod).

5. **DASHBOARD HIERARCHY: SERVICE → COMPONENT → DETAIL** — Top-level dashboard per service (health overview). Drill-down per component (API, database, cache). Detail view per instance. Make the top-level actionable from a phone at 3am.

6. **NO AI TOOL REFERENCES** — No mentions in alarm descriptions, dashboard names, or metric filter patterns. Output reads as SRE work.

---

## Alarm Design Tiers

| Tier | Severity | Response | Examples |
|------|----------|----------|---------|
| P0 | Critical | Page on-call immediately | API 5xx > 5%, DB connections exhausted |
| P1 | High | Notify within 5 minutes | CPU > 90%, memory > 85%, latency p99 > 2s |
| P2 | Medium | Ticket, investigate next business day | Cost anomaly, slow queries, non-fatal errors |
| P3 | Low | Review weekly | Under-utilized resources, deprecated APIs |

---

## Terraform: SNS Topics and Alarms

```hcl
resource "aws_sns_topic" "pagerduty_critical" {
  name = "${var.project}-critical-alerts"
}

resource "aws_sns_topic" "team_alerts" {
  name = "${var.project}-team-alerts"
}

# Example: ALB 5xx error rate alarm
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  alarm_name          = "${var.project}-alb-5xx-high"
  alarm_description   = "ALB 5XX error rate > 5% for 5 minutes — investigate API errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 5
  treat_missing_data  = "notBreaching"

  metric_query {
    id          = "m1"
    return_data = false
    metric {
      metric_name = "HTTPCode_Target_5XX_Count"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
    }
  }

  metric_query {
    id          = "m2"
    return_data = false
    metric {
      metric_name = "RequestCount"
      namespace   = "AWS/ApplicationELB"
      period      = 300
      stat        = "Sum"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
    }
  }

  metric_query {
    id          = "e1"
    return_data = true
    expression  = "IF(m2>10, 100*m1/m2, 0)"
    label       = "5XX Error Rate %"
  }

  alarm_actions = [aws_sns_topic.pagerduty_critical.arn]
  ok_actions    = [aws_sns_topic.pagerduty_critical.arn]
}
```

---

## Terraform: Anomaly Detection Alarm

```hcl
resource "aws_cloudwatch_metric_alarm" "latency_anomaly" {
  alarm_name          = "${var.project}-api-latency-anomaly"
  alarm_description   = "API latency deviating from historical baseline"
  comparison_operator = "GreaterThanUpperThreshold"
  evaluation_periods  = 3
  treat_missing_data  = "notBreaching"
  threshold_metric_id = "ad1"

  metric_query {
    id          = "m1"
    return_data = true
    metric {
      metric_name = "TargetResponseTime"
      namespace   = "AWS/ApplicationELB"
      period      = 60
      stat        = "p99"
      dimensions  = { LoadBalancer = aws_lb.main.arn_suffix }
    }
  }

  metric_query {
    id         = "ad1"
    expression = "ANOMALY_DETECTION_BAND(m1, 2)"  # 2 standard deviations
    label      = "TargetResponseTime (expected)"
  }

  alarm_actions = [aws_sns_topic.team_alerts.arn]
}
```

---

## Terraform: Composite Alarm

```hcl
resource "aws_cloudwatch_composite_alarm" "api_degraded" {
  alarm_name        = "${var.project}-api-degraded"
  alarm_description = "API is degraded: high error rate AND elevated latency together"

  alarm_rule = "ALARM(${aws_cloudwatch_metric_alarm.alb_5xx.alarm_name}) AND ALARM(${aws_cloudwatch_metric_alarm.latency_anomaly.alarm_name})"

  alarm_actions = [aws_sns_topic.pagerduty_critical.arn]
  ok_actions    = [aws_sns_topic.pagerduty_critical.arn]
}
```

---

## Terraform: Log Groups with Retention

```hcl
locals {
  log_groups = {
    app     = { name = "/app/${var.project}/${var.environment}", retention = 90 }
    ecs     = { name = "/ecs/${var.project}/${var.environment}", retention = 30 }
    lambda  = { name = "/aws/lambda/${var.project}-${var.environment}", retention = 30 }
    rds     = { name = "/aws/rds/${var.project}-${var.environment}/error", retention = 90 }
    vpc_flow = { name = "/vpc/flow-logs/${var.vpc_id}", retention = 30 }
  }
}

resource "aws_cloudwatch_log_group" "main" {
  for_each = local.log_groups

  name              = each.value.name
  retention_in_days = each.value.retention
  kms_key_id        = aws_kms_key.logs.arn

  tags = {
    Name        = each.key
    Environment = var.environment
  }
}
```

---

## Terraform: CloudWatch Dashboard

```hcl
resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${var.project}-${var.environment}"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "text"
        properties = { markdown = "# ${var.project} ${var.environment} — Overview Dashboard" }
        x = 0; y = 0; width = 24; height = 1
      },
      {
        type = "alarm"
        properties = {
          title  = "Active Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.alb_5xx.arn,
            aws_cloudwatch_metric_alarm.latency_anomaly.arn
          ]
        }
        x = 0; y = 1; width = 24; height = 2
      },
      {
        type = "metric"
        properties = {
          title  = "Request Rate & Error Rate"
          period = 60
          stat   = "Sum"
          view   = "timeSeries"
          metrics = [
            ["AWS/ApplicationELB", "RequestCount", "LoadBalancer", aws_lb.main.arn_suffix],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix, { color = "#d62728" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_4XX_Count", "LoadBalancer", aws_lb.main.arn_suffix, { color = "#ff7f0e" }]
          ]
        }
        x = 0; y = 3; width = 12; height = 6
      },
      {
        type = "metric"
        properties = {
          title  = "Latency Percentiles"
          period = 60
          view   = "timeSeries"
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p50", label = "p50" }],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p95", label = "p95" }],
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p99", label = "p99", color = "#d62728" }]
          ]
        }
        x = 12; y = 3; width = 12; height = 6
      },
      {
        type = "metric"
        properties = {
          title  = "RDS CPU & Connections"
          period = 60
          view   = "timeSeries"
          metrics = [
            ["AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", aws_db_instance.main.id],
            ["AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", aws_db_instance.main.id]
          ]
        }
        x = 0; y = 9; width = 12; height = 6
      }
    ]
  })
}
```

---

## Container Insights for ECS

```hcl
resource "aws_ecs_cluster" "main" {
  name = "${var.project}-${var.environment}"

  setting {
    name  = "containerInsights"
    value = "enabled"  # Enable Container Insights
  }
}

# Container Insights provides these metrics automatically:
# ContainerInsights/ECS: CpuUtilized, MemoryUtilized, NetworkRxBytes, NetworkTxBytes
# ContainerInsights/ECS: ContainerInstanceCount, ServiceCount, RunningTaskCount
```

---

## CloudWatch Logs Insights Queries

```sql
-- Top 10 slowest API endpoints (from application logs in JSON format)
fields @timestamp, path, method, duration_ms
| filter duration_ms > 500
| stats avg(duration_ms) as avg_ms, max(duration_ms) as max_ms, count() as requests by path, method
| sort avg_ms desc
| limit 10

-- Error rate by endpoint
fields @timestamp, path, status_code
| filter status_code >= 400
| stats count() as errors by path, status_code
| sort errors desc
| limit 20

-- Lambda cold start analysis
filter @message like /Init Duration/
| parse @message "Init Duration: * ms" as initDuration
| stats avg(initDuration), max(initDuration), count() as coldStarts by bin(5min)

-- VPC flow logs — top talkers
fields srcAddr, dstAddr, bytes
| stats sum(bytes) as total_bytes by srcAddr, dstAddr
| sort total_bytes desc
| limit 20
```

---

## Synthetics Canary (Availability Monitoring)

```hcl
resource "aws_synthetics_canary" "api_health" {
  name                 = "${var.project}-api-health"
  artifact_s3_location = "s3://${aws_s3_bucket.canary_artifacts.id}/canary/"
  execution_role_arn   = aws_iam_role.canary.arn
  handler              = "apiCanary.handler"
  zip_file             = filebase64("${path.module}/canary/api_check.zip")
  runtime_version      = "syn-nodejs-puppeteer-6.2"
  start_canary         = true

  schedule {
    expression          = "rate(5 minutes)"
    duration_in_seconds = 0
  }

  success_retention_period = 2   # Days
  failure_retention_period = 14  # Days

  run_config {
    timeout_in_seconds = 60
    memory_in_mb       = 960
  }
}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| Metrics (standard) | First 10 metrics free, $0.30/metric/month |
| Metrics (custom) | $0.30/metric/month |
| Alarms | $0.10/alarm/month (standard), $0.30 (high-res) |
| Dashboard | $3.00/dashboard/month (first 3 free) |
| Log data ingestion | $0.50/GB |
| Log storage | $0.03/GB/month |
| Log Insights queries | $0.005/GB scanned |
| Container Insights | $0.50/instance/month |
| Synthetics canary | $0.0012/run |

**Optimization:** Use metric math instead of custom metrics; set log retention aggressively; query logs with time-bounded filters to reduce Insights scan cost.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Alarm with no action | Every alarm must have SNS action |
| Default log retention (never expires) | Set retention_in_days on every log group |
| Simple threshold alarms firing constantly | Use composite alarms or anomaly detection |
| treat_missing_data = "notBreaching" for availability | Use "breaching" when missing = down |
| No p99 latency alarm (only p50) | Median hides tail latency; always alarm on p95/p99 |
| Not using Container Insights for ECS | Enable it — free with standard metric rates |
| Dashboard without alarm widget at top | First widget should show current alarm state |

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
