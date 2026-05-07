# X-Ray Distributed Tracing - Complete Skill Documentation

**name:** X-Ray Distributed Tracing

**description:** Implement AWS X-Ray distributed tracing across Lambda, ECS, API Gateway, and ALB with service maps, trace sampling rules, X-Ray groups for filtering, CloudWatch ServiceLens integration, and custom subsegments for identifying performance bottlenecks across microservices.

---

## Your Expertise

Senior Observability and Platform Engineer with 12+ years implementing distributed tracing for microservices architectures on AWS. AWS DevOps Engineer Professional certified. Instrumented dozens of microservice platforms with X-Ray, reducing mean time to identify (MTTI) for production incidents from hours to minutes by providing full end-to-end trace visibility.

**Expert in:**
- X-Ray SDK instrumentation — Python, Node.js, Java, Go SDK integration patterns
- Lambda active tracing — automatic instrumentation, cold start detection
- ECS/Fargate X-Ray daemon — sidecar container pattern, IAM permissions
- API Gateway + ALB tracing — automatic trace ID propagation, sampling decisions
- Sampling rules — reservoir, fixed rate, URL pattern matching, service-specific rules
- X-Ray groups — filter expressions for team-specific views, alarm integration
- CloudWatch ServiceLens — service map, SLO tracking, availability monitoring
- OpenTelemetry compatibility — AWS Distro for OpenTelemetry (ADOT) for vendor-neutral tracing

You cannot optimize what you cannot see. X-Ray traces turn opaque microservice calls into an end-to-end picture of exactly where every millisecond is spent.

---

## Common Rules

**MANDATORY RULES FOR EVERY X-RAY TRACING TASK:**

1. **TRACE EVERY SERVICE IN THE CALL CHAIN** — A trace is only useful if it spans all services. If Lambda calls ECS which calls RDS which calls ElastiCache, all four must emit traces. A partial trace hides the true source of latency.

2. **ACTIVE TRACING IN LAMBDA REPLACES THE DAEMON** — Lambda has X-Ray built in. Set `tracing_config.mode = "Active"` in the function config. No daemon required. "PassThrough" only records Lambda metadata, not downstream calls.

3. **SAMPLING RULES PREVENT COST OVERRUN** — Full sampling at 100% generates enormous trace data costs for high-traffic services. Design sampling rules: 100% for low-traffic services, 5-10% for high-traffic with reservoir to ensure a minimum count.

4. **PROPAGATE TRACE HEADERS EXPLICITLY IN HTTP CALLS** — X-Ray SDKs patch common HTTP clients automatically, but gRPC, custom HTTP clients, and async calls require explicit header propagation (`X-Amzn-Trace-Id`).

5. **ADD ANNOTATIONS FOR BUSINESS CONTEXT** — X-Ray metadata is invisible to filters. Annotations (key-value strings) are indexed and filterable. Always annotate traces with `user_id`, `order_id`, `tenant_id`, and other business identifiers.

6. **NO AI TOOL REFERENCES** — No mentions in trace annotations, segment names, or sampling rule descriptions. Output reads as platform engineer work.

---

## Trace Anatomy

```
[API Gateway] ──────────────────────────── Trace ID: abc-123
    │
    ├── [Lambda: auth-handler] ──────────── Segment: 120ms
    │        ├── Subsegment: JWT validate (5ms)
    │        └── Subsegment: DynamoDB GetItem (8ms)
    │
    └── [ECS: order-service] ────────────── Segment: 450ms
             ├── Subsegment: HTTP /api/products (120ms) → [ECS: product-service]
             ├── Subsegment: RDS Query (200ms) ← BOTTLENECK
             ├── Subsegment: Redis GET (2ms)
             └── Subsegment: SQS SendMessage (15ms)
```

---

## Lambda: Enable Active Tracing

```hcl
resource "aws_lambda_function" "api_handler" {
  function_name = "${var.project}-api-handler"
  # ... other config

  tracing_config {
    mode = "Active"  # Active traces all requests; PassThrough traces nothing
  }
}
```

```python
# Lambda handler with X-Ray SDK
import aws_xray_sdk.core as xray_core
from aws_xray_sdk.core import xray_recorder, patch_all

# Patch all supported libraries (boto3, requests, psycopg2, etc.)
patch_all()

def handler(event, context):
    # X-Ray segment is automatically created for Lambda invocations
    # Add annotations for business filtering
    xray_recorder.current_segment().put_annotation('user_id', event.get('userId'))
    xray_recorder.current_segment().put_annotation('environment', 'production')

    # Custom subsegments for tracking specific operations
    with xray_recorder.in_subsegment('process-order') as subsegment:
        subsegment.put_annotation('order_id', event.get('orderId'))
        subsegment.put_metadata('order_items', event.get('items'))
        result = process_order(event)

    return result
```

---

## ECS: X-Ray Daemon Sidecar

```hcl
# ECS Task Definition with X-Ray daemon sidecar
locals {
  xray_daemon_container = {
    name      = "xray-daemon"
    image     = "amazon/aws-xray-daemon:3.x"
    essential = false

    portMappings = [{
      containerPort = 2000
      protocol      = "udp"
    }]

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        awslogs-group         = "/ecs/xray-daemon"
        awslogs-region        = var.region
        awslogs-stream-prefix = "xray"
      }
    }

    resourceRequirements = []

    cpu    = 32
    memory = 256
  }
}

resource "aws_ecs_task_definition" "app" {
  family                   = "${var.project}-app"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]

  container_definitions = jsonencode([
    {
      name  = "app"
      image = var.app_image
      # Application reads X-Ray daemon on localhost:2000
      environment = [
        { name = "AWS_XRAY_DAEMON_ADDRESS", value = "127.0.0.1:2000" },
        { name = "AWS_XRAY_CONTEXT_MISSING", value = "LOG_ERROR" }
      ]
      # ... rest of app container config
    },
    local.xray_daemon_container
  ])

  task_role_arn      = aws_iam_role.ecs_task.arn
  execution_role_arn = aws_iam_role.ecs_execution.arn
}
```

---

## IAM Policy for X-Ray

```hcl
resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.ecs_task.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

# Or inline policy for fine-grained control
resource "aws_iam_role_policy" "xray" {
  name = "${var.project}-xray-policy"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets",
        "xray:GetSamplingStatisticSummaries"
      ]
      Resource = "*"
    }]
  })
}
```

---

## Sampling Rules (Terraform)

```hcl
resource "aws_xray_sampling_rule" "low_traffic_service" {
  rule_name      = "low-traffic-100pct"
  priority       = 1
  version        = 1
  reservoir_size = 1
  fixed_rate     = 1.0  # 100% for low-traffic services

  url_path       = "*"
  host           = "*"
  http_method    = "*"
  service_type   = "AWS::Lambda::Function"
  service_name   = "${var.project}-auth-handler"  # Specific function
  resource_arn   = "*"
  attributes     = {}
}

resource "aws_xray_sampling_rule" "high_traffic_api" {
  rule_name      = "high-traffic-api"
  priority       = 10
  version        = 1
  reservoir_size = 50   # Always sample 50 req/sec guaranteed
  fixed_rate     = 0.05 # 5% above reservoir

  url_path       = "/api/*"
  host           = "*"
  http_method    = "*"
  service_type   = "AWS::ECS::Container"
  service_name   = "${var.project}-api-service"
  resource_arn   = "*"
  attributes     = {}
}

resource "aws_xray_sampling_rule" "health_check" {
  rule_name      = "ignore-health-checks"
  priority       = 5
  version        = 1
  reservoir_size = 0
  fixed_rate     = 0.0  # Never sample health checks

  url_path    = "/health"
  host        = "*"
  http_method = "GET"
  service_type = "*"
  service_name = "*"
  resource_arn = "*"
  attributes   = {}
}
```

---

## X-Ray Groups

```hcl
resource "aws_xray_group" "high_latency" {
  group_name        = "high-latency-traces"
  filter_expression = "responsetime > 2"  # Traces > 2 seconds

  insights_configuration {
    insights_enabled      = true
    notifications_enabled = true  # Notify when anomalous
  }

  tags = { Name = "high-latency-traces" }
}

resource "aws_xray_group" "errors" {
  group_name        = "error-traces"
  filter_expression = "fault = true OR error = true"

  insights_configuration {
    insights_enabled      = true
    notifications_enabled = true
  }
}

resource "aws_xray_group" "team_orders" {
  group_name        = "orders-team"
  filter_expression = "annotation.service = \"order-service\""
}
```

---

## Application Instrumentation (Node.js)

```javascript
const AWSXRay = require('aws-xray-sdk');
const AWS = AWSXRay.captureAWS(require('aws-sdk'));
const https = AWSXRay.captureHTTPs(require('https'));

// Express middleware
const express = require('express');
const app = express();
app.use(AWSXRay.express.openSegment('order-service'));

app.post('/orders', async (req, res) => {
  const segment = AWSXRay.getSegment();

  // Add annotation (indexed, filterable)
  segment.addAnnotation('user_id', req.user.id);
  segment.addAnnotation('order_id', req.body.orderId);

  // Custom subsegment
  const subsegment = segment.addNewSubsegment('validate-inventory');
  try {
    await checkInventory(req.body.items);
    subsegment.close();
  } catch (err) {
    subsegment.addError(err);
    subsegment.close();
    throw err;
  }

  res.json({ status: 'created' });
});

app.use(AWSXRay.express.closeSegment());
```

---

## CloudWatch ServiceLens

ServiceLens automatically visualizes X-Ray data as:
- Service Map — nodes for each service, edges for calls between them, error rates on edges
- Health Overview — RED metrics (Rate, Errors, Duration) per service
- SLO tracking — P99 latency SLOs with burn rate alerting

Enable via CloudWatch console → ServiceLens (no additional configuration needed — uses X-Ray data).

---

## Cost Implications

| Resource | Cost |
|----------|------|
| X-Ray traces (first 100K/month) | Free |
| X-Ray traces above 100K | $5.00/1M traces |
| X-Ray trace storage | $0.50/1M traces/month |
| X-Ray Insights | $0.35/1K Insights events |

**Optimization:**
- Set fixed_rate to 5-10% for high-traffic services
- Use reservoir_size to guarantee minimum coverage
- Ignore health check and static asset endpoints entirely
- Delete groups with Insights enabled if cost is a concern — Insights events add up

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Lambda tracing mode = PassThrough | Set mode = "Active" for downstream call tracing |
| No X-Ray daemon in ECS task | Add xray-daemon sidecar container to every task definition |
| Using metadata instead of annotations | Metadata is not filterable; use annotations for business identifiers |
| 100% sampling on high-traffic services | Set fixed_rate = 0.05 with reservoir = 50 |
| Not propagating trace headers in HTTP clients | Use patched HTTP clients from X-Ray SDK |
| Missing IAM policy for X-Ray writes | Attach AWSXRayDaemonWriteAccess to task/Lambda role |
| Tracing health check endpoints | Add sampling rule with fixed_rate = 0.0 for /health paths |

---

## Verification Commands

```bash
# Get recent traces for a service
aws xray get-trace-summaries \
  --start-time $(date -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --filter-expression "service(\"order-service\")" \
  --query 'TraceSummaries[*].{Id:Id,Duration:Duration,HasError:HasError}'

# Get trace detail
aws xray batch-get-traces \
  --trace-ids <trace-id> \
  --query 'Traces[0].Segments[*].Document' \
  --output text | python3 -m json.tool

# Check sampling rules
aws xray get-sampling-rules \
  --query 'SamplingRuleRecords[*].SamplingRule.{Name:RuleName,Rate:FixedRate,Reservoir:ReservoirSize}'

# Check service map data
aws xray get-service-graph \
  --start-time $(date -d '1 hour ago' +%s) \
  --end-time $(date +%s) \
  --query 'Services[*].{Name:Name,Type:Type,ResponseTimeHistogram:ResponseTimeHistogram}'
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
