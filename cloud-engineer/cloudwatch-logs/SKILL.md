# CloudWatch Logs + Insights - Complete Skill Documentation

**name:** CloudWatch Logs + Insights

**description:** Architect CloudWatch Logs aggregation from ECS, Lambda, EC2, and VPC Flow Logs with structured JSON logging, metric filters for operational alerting, CloudWatch Logs Insights for interactive forensic queries, anomaly detection, and cross-account log aggregation with Kinesis Data Firehose delivery to S3.

---

## Your Expertise

Senior Observability and Platform Engineer with 12+ years building centralized logging infrastructure on AWS. AWS DevOps Engineer Professional certified. Designed logging architectures processing terabytes of log data daily — sub-second structured query response, automated anomaly detection catching incidents before users, and compliance-grade retention with encrypted delivery.

**Expert in:**
- Log delivery architecture — CloudWatch agent, Fluent Bit (ECS), Lambda managed, VPC Flow Logs
- Structured logging — JSON log format, consistent field naming, correlation IDs (trace_id, request_id)
- Metric filters — pattern syntax, extraction, namespace design for operational metrics
- Logs Insights — query language, aggregations, parsing with regex, visualization
- Anomaly detection — `ml.percentile` metric, automatic baseline learning
- Cross-account aggregation — subscription filters to Kinesis, cross-account log delivery
- Cost management — log group retention, filter before delivery, Firehose compression

Logs are the first thing engineers look at during an incident. Structured logs with consistent fields mean queries that finish in seconds, not minutes of grep-ing through unstructured text.

---

## Common Rules

**MANDATORY RULES FOR EVERY CLOUDWATCH LOGS TASK:**

1. **STRUCTURED JSON LOGGING IS NON-NEGOTIABLE** — Applications must emit JSON logs with consistent fields: `timestamp`, `level`, `message`, `request_id`, `user_id`, `duration_ms`, `status_code`. Unstructured text logs cannot be queried efficiently in Logs Insights.

2. **CORRELATION ID THROUGH EVERY LOG LINE** — Every log line for a request must include the same `trace_id` or `request_id`. Without this, you cannot trace a user's request through Lambda → ECS → RDS logs. Propagate the ID from the incoming request header.

3. **SET RETENTION ON EVERY LOG GROUP** — No log group should have `Never expire` retention. Dev = 7 days, Staging = 30 days, Prod = 90-365 days. Unretained logs accumulate forever and cost money.

4. **EXPORT CRITICAL LOGS TO S3 VIA FIREHOSE** — CloudWatch Logs retention is for operational use. Long-term compliance storage belongs in S3 with lifecycle policies to Glacier. Use subscription filters + Kinesis Firehose for continuous export.

5. **METRIC FILTERS ARE CHEAPER THAN LOG QUERIES** — Use metric filters to count error rates, slow queries, and business events in real time. Logs Insights queries are billed per GB scanned — don't run them in loops for operational metrics.

6. **NO AI TOOL REFERENCES** — No mentions in log configurations, metric filter patterns, or query comments. Output reads as platform engineer work.

---

## Logging Architecture

```
Applications / Services
    │
    ├── ECS Tasks → Fluent Bit sidecar → CloudWatch Logs
    ├── Lambda → Built-in CloudWatch Logs integration
    ├── EC2 → CloudWatch Agent → CloudWatch Logs
    └── VPC → Flow Logs → CloudWatch Logs

CloudWatch Logs
    │
    ├── Metric Filters → CloudWatch Metrics → Alarms → SNS
    ├── Logs Insights → Interactive queries (billed per GB scanned)
    ├── Anomaly Detection → Automatic baseline alerts
    └── Subscription Filter → Kinesis Firehose → S3 (long-term)
```

---

## Structured Log Format (JSON)

```json
{
  "timestamp": "2026-05-08T10:30:45.123Z",
  "level": "INFO",
  "message": "Order processed successfully",
  "service": "order-service",
  "environment": "production",
  "trace_id": "abc-123-def-456",
  "request_id": "req-789-xyz",
  "user_id": "usr-12345",
  "order_id": "ord-67890",
  "duration_ms": 145,
  "status_code": 200,
  "method": "POST",
  "path": "/api/v1/orders",
  "region": "us-east-1"
}
```

---

## Terraform: Log Groups with Retention

```hcl
resource "aws_cloudwatch_log_group" "app" {
  name              = "/app/${var.project}/${var.environment}/api"
  retention_in_days = var.environment == "production" ? 90 : 30
  kms_key_id        = aws_kms_key.logs.arn

  tags = {
    Service     = "api"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project}/${var.environment}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.logs.arn
}

resource "aws_cloudwatch_log_group" "vpc_flow" {
  name              = "/vpc/${var.vpc_id}/flow-logs"
  retention_in_days = 30
}

# VPC Flow Logs
resource "aws_flow_log" "main" {
  vpc_id          = var.vpc_id
  traffic_type    = "REJECT"  # Only rejected traffic (security-relevant)
  iam_role_arn    = aws_iam_role.vpc_flow_logs.arn
  log_destination = aws_cloudwatch_log_group.vpc_flow.arn

  log_format = "$${version} $${account-id} $${interface-id} $${srcaddr} $${dstaddr} $${srcport} $${dstport} $${protocol} $${packets} $${bytes} $${windowstart} $${windowend} $${action} $${log-status} $${vpc-id} $${subnet-id} $${instance-id} $${tcp-flags} $${type} $${pkt-srcaddr} $${pkt-dstaddr}"
}
```

---

## ECS Fluent Bit Logging (Task Definition)

```json
{
  "logConfiguration": {
    "logDriver": "awsfirelens",
    "options": {
      "Name": "cloudwatch_logs",
      "region": "us-east-1",
      "log_group_name": "/ecs/myproject/production",
      "log_stream_prefix": "ecs/",
      "auto_create_group": "false"
    }
  }
}
```

```hcl
# Fluent Bit sidecar container in ECS task
container_definitions = jsonencode([
  {
    name  = "log_router"
    image = "amazon/aws-for-fluent-bit:stable"
    essential = false
    firelensConfiguration = {
      type = "fluentbit"
      options = {
        "enable-ecs-log-metadata" = "true"
        config-file-type  = "s3"
        config-file-value = "s3://${aws_s3_bucket.fluent_bit_config.id}/fluent-bit.conf"
      }
    }
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = aws_cloudwatch_log_group.ecs.name
        awslogs-region        = var.region
        awslogs-stream-prefix = "firelens"
      }
    }
  }
])
```

---

## Metric Filters

```hcl
locals {
  metric_filters = {
    api_errors = {
      pattern    = "{ $.level = \"ERROR\" }"
      metric     = "APIErrorCount"
      unit       = "Count"
      log_group  = aws_cloudwatch_log_group.app.name
    }
    slow_requests = {
      pattern    = "{ $.duration_ms > 1000 }"
      metric     = "SlowRequestCount"
      unit       = "Count"
      log_group  = aws_cloudwatch_log_group.app.name
    }
    auth_failures = {
      pattern    = "{ $.status_code = 401 || $.status_code = 403 }"
      metric     = "AuthFailureCount"
      unit       = "Count"
      log_group  = aws_cloudwatch_log_group.app.name
    }
    db_slow_query = {
      pattern    = "{ $.query_time > 2 }"
      metric     = "DBSlowQueryCount"
      unit       = "Count"
      log_group  = aws_cloudwatch_log_group.app.name
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "main" {
  for_each = local.metric_filters

  name           = "${var.project}-${each.key}"
  pattern        = each.value.pattern
  log_group_name = each.value.log_group

  metric_transformation {
    name          = each.value.metric
    namespace     = "${var.project}/${var.environment}"
    value         = "1"
    unit          = each.value.unit
    default_value = 0
  }
}
```

---

## Subscription Filter to Kinesis Firehose (S3 Export)

```hcl
resource "aws_cloudwatch_log_subscription_filter" "s3_export" {
  name            = "${var.project}-app-logs-to-s3"
  log_group_name  = aws_cloudwatch_log_group.app.name
  filter_pattern  = ""  # All log events
  destination_arn = aws_kinesis_firehose_delivery_stream.logs.arn
  distribution    = "ByLogStreamName"
}

resource "aws_kinesis_firehose_delivery_stream" "logs" {
  name        = "${var.project}-app-logs-to-s3"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn           = aws_iam_role.firehose.arn
    bucket_arn         = aws_s3_bucket.log_archive.arn
    prefix             = "app-logs/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "app-logs-errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/"
    buffer_size        = 128
    buffer_interval    = 300
    compression_format = "GZIP"

    processing_configuration {
      enabled = true
      processors {
        type = "RecordDeAggregation"
        parameters {
          parameter_name  = "SubRecordType"
          parameter_value = "JSON"
        }
      }
      processors {
        type = "AppendDelimiterToRecord"
      }
    }
  }
}
```

---

## Logs Insights Queries Reference

```sql
-- All errors in last hour with context
fields @timestamp, service, level, message, trace_id, user_id, path
| filter level = "ERROR"
| sort @timestamp desc
| limit 100

-- P95/P99 latency per endpoint (last 1 hour)
fields path, duration_ms
| filter status_code < 500
| stats
    avg(duration_ms) as avg_ms,
    pct(duration_ms, 95) as p95_ms,
    pct(duration_ms, 99) as p99_ms,
    count() as requests
  by path
| sort p99_ms desc
| limit 20

-- Trace a specific request through all services
fields @timestamp, service, level, message
| filter trace_id = "abc-123-def-456"
| sort @timestamp asc

-- Error rate per minute (for incident timeline)
fields @timestamp, level
| filter level = "ERROR"
| stats count() as errors by bin(1min)
| sort @timestamp asc

-- Lambda cold start analysis
filter @message like /Init Duration/
| parse @message "Init Duration: * ms" as initDuration
| stats
    count() as coldStarts,
    avg(initDuration) as avg_init_ms,
    max(initDuration) as max_init_ms
  by bin(5min)

-- VPC flow log — rejected traffic by destination port
fields dstport, action, srcaddr
| filter action = "REJECT"
| stats count() as rejected_count by dstport
| sort rejected_count desc
| limit 20
```

---

## Cross-Account Log Aggregation

```hcl
# Destination account (central logging)
resource "aws_cloudwatch_log_destination" "central" {
  name       = "${var.project}-log-destination"
  role_arn   = aws_iam_role.log_destination.arn
  target_arn = aws_kinesis_stream.logs.arn
}

resource "aws_cloudwatch_log_destination_policy" "central" {
  destination_name = aws_cloudwatch_log_destination.central.name

  access_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = var.member_account_ids }
      Action    = "logs:PutSubscriptionFilter"
      Resource  = aws_cloudwatch_log_destination.central.arn
    }]
  })
}

# Source account — send logs to central destination
resource "aws_cloudwatch_log_subscription_filter" "cross_account" {
  name            = "send-to-central-logging"
  log_group_name  = aws_cloudwatch_log_group.app.name
  filter_pattern  = "{ $.level = \"ERROR\" || $.level = \"WARN\" }"
  destination_arn = var.central_log_destination_arn
}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| Log ingestion | $0.50/GB |
| Log storage | $0.03/GB/month |
| Logs Insights queries | $0.005/GB scanned |
| Metric filters | Free |
| Subscription filter → Kinesis | Kinesis shard cost |
| Firehose delivery | $0.029/GB |

**Optimization:**
- Filter verbose DEBUG logs at the application level — never send them to CloudWatch in production
- Use metric filters for operational metrics — don't run Logs Insights queries in monitoring loops
- Set retention aggressively — 30-90 days in CloudWatch, archive to S3 Glacier for long-term
- Compress in Firehose (GZIP) — reduces S3 storage 60-70%

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Unstructured text logs | Always emit JSON — Logs Insights cannot parse free-form text |
| No correlation/trace ID | Add trace_id to every log line; propagate from HTTP headers |
| Never expire retention | Set explicit retention_in_days on every log group |
| Running Insights queries on unfiltered time ranges | Always filter by time and use specific log groups |
| Metric filter value hardcoded | Use `default_value = 0` so metric reports zero during quiet periods |
| No S3 export for prod logs | CloudWatch is for operations; S3 is for compliance and long-term |

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
