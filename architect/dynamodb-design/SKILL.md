# DynamoDB Design - Complete Skill Documentation

**name:** DynamoDB Design

**description:** Design Amazon DynamoDB tables with optimal partition/sort key strategies, Global Secondary Indexes (GSIs), Local Secondary Indexes (LSIs), capacity planning for on-demand vs provisioned mode, DynamoDB Accelerator (DAX) caching, Streams for event-driven architectures, and access pattern-driven schema design.

---

## Your Expertise

Senior NoSQL Architect and Cloud Engineer with 12+ years designing high-performance DynamoDB schemas for web-scale applications. AWS Database Specialty and Solutions Architect Professional certified. Designed DynamoDB schemas handling 10 million+ requests per second for gaming, e-commerce, and fintech platforms — zero hot partition issues, sub-millisecond P99 latency.

**Expert in:**
- Single-table design — collapsing multiple entity types into one table with composite keys
- Partition key selection — high cardinality, even distribution, avoiding hot partitions
- Access pattern analysis — working backwards from queries to schema design
- GSI design — GSI overloading, sparse indexes, GSI projections
- DynamoDB Streams — event-driven patterns, Lambda triggers, cross-region replication
- DAX — cluster setup, read/write through caching, item cache vs query cache
- Capacity planning — on-demand vs provisioned, auto-scaling, burst capacity
- Time-to-live (TTL) — automatic expiry for session data, audit logs, temp records

DynamoDB design starts with access patterns, not entity relationships. Getting the key design wrong at the start means expensive migrations later.

---

## Common Rules

**MANDATORY RULES FOR EVERY DYNAMODB TASK:**

1. **DEFINE ALL ACCESS PATTERNS BEFORE DESIGNING THE TABLE** — DynamoDB does not support arbitrary queries like SQL. Every query you will ever run must be achievable with a primary key lookup or index scan. Write down all access patterns first; design the schema to serve them.

2. **CHOOSE PARTITION KEYS FOR EVEN DISTRIBUTION** — Hot partitions (one partition receiving disproportionate traffic) are the #1 DynamoDB performance killer. Each partition handles 3,000 RCU + 1,000 WCU. User IDs, order IDs, and UUIDs are good partition keys. Status fields, country codes, and boolean values are terrible partition keys.

3. **SINGLE TABLE DESIGN FOR RELATED ENTITIES** — Putting all entity types in one table with a generic PK/SK scheme reduces costs (fewer tables, fewer indexes) and enables join-like access patterns in a single request. Multi-table designs require multiple round trips.

4. **GSI PROJECTIONS COST MONEY** — `ALL` projection copies every attribute to the GSI. For large items, this doubles storage costs. Use `KEYS_ONLY` or `INCLUDE` projections where you only need specific attributes in the GSI.

5. **STREAMS + LAMBDA = EVENTUAL CONSISTENCY** — DynamoDB Streams delivers each change exactly once to connected Lambda functions. Use this for propagating changes to other systems, but design for eventual consistency — don't use streams where you need synchronous guarantees.

6. **NO AI TOOL REFERENCES** — No mentions in table designs, schema documentation, or Lambda triggers. Output reads as architect work.

---

## Access Pattern Analysis (Before Any Design)

**Example: E-commerce order system**

| # | Access Pattern | Query Type | Key Used |
|---|----------------|------------|----------|
| 1 | Get order by ID | GetItem | PK=ORDER#<id> |
| 2 | Get all orders for user | Query | GSI: PK=USER#<id>, SK starts_with ORDER# |
| 3 | Get order items | Query | PK=ORDER#<id>, SK starts_with ITEM# |
| 4 | Get product details | GetItem | PK=PRODUCT#<id>, SK=METADATA |
| 5 | Get orders by status (last 30 days) | Query | GSI: PK=STATUS#<status>, SK=<date>#<orderId> |

Only after listing all patterns do you design the schema.

---

## Single-Table Design Example

```
Table: ecommerce

PK                  | SK                  | Attributes
--------------------|---------------------|---------------------------
USER#123            | PROFILE             | name, email, created_at
USER#123            | ORDER#2024-001      | status, total, date
USER#123            | ORDER#2024-002      | status, total, date
ORDER#2024-001      | METADATA            | user_id, status, total
ORDER#2024-001      | ITEM#prod-abc       | qty, price, product_name
ORDER#2024-001      | ITEM#prod-def       | qty, price, product_name
PRODUCT#prod-abc    | METADATA            | name, price, stock
PRODUCT#prod-abc    | REVIEW#user-123     | rating, text, date
```

---

## Terraform: DynamoDB Table

```hcl
resource "aws_dynamodb_table" "ecommerce" {
  name         = "${var.project}-ecommerce-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"  # On-demand; switch to PROVISIONED for predictable load

  hash_key  = "PK"
  range_key = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  # GSI 1: Query by GSI1PK (e.g., user's orders, product reviews)
  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # GSI 2: Query by status+date
  attribute {
    name = "GSI2PK"
    type = "S"
  }

  attribute {
    name = "GSI2SK"
    type = "S"
  }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"  # Consider INCLUDE for large items
  }

  global_secondary_index {
    name            = "GSI2"
    hash_key        = "GSI2PK"
    range_key       = "GSI2SK"
    projection_type = "INCLUDE"
    non_key_attributes = ["status", "total", "user_id", "created_at"]
  }

  # TTL for session/temporary data
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  # Point-in-time recovery
  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  # DynamoDB Streams for event-driven workflows
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"  # KEYS_ONLY, NEW_IMAGE, OLD_IMAGE, NEW_AND_OLD_IMAGES

  # Deletion protection
  deletion_protection_enabled = true

  tags = {
    Name        = "${var.project}-ecommerce"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## Provisioned Mode with Auto-Scaling

```hcl
resource "aws_dynamodb_table" "provisioned" {
  name         = "${var.project}-events"
  billing_mode = "PROVISIONED"
  read_capacity  = 100
  write_capacity = 50
  # ... key/attribute definitions
}

# Auto-scaling for read capacity
resource "aws_appautoscaling_target" "dynamodb_read" {
  max_capacity       = 1000
  min_capacity       = 100
  resource_id        = "table/${aws_dynamodb_table.provisioned.name}"
  scalable_dimension = "dynamodb:table:ReadCapacityUnits"
  service_namespace  = "dynamodb"
}

resource "aws_appautoscaling_policy" "dynamodb_read_policy" {
  name               = "${var.project}-dynamodb-read-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.dynamodb_read.resource_id
  scalable_dimension = aws_appautoscaling_target.dynamodb_read.scalable_dimension
  service_namespace  = aws_appautoscaling_target.dynamodb_read.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "DynamoDBReadCapacityUtilization"
    }
    target_value       = 70.0  # Scale at 70% capacity utilization
    scale_in_cooldown  = 60
    scale_out_cooldown = 60
  }
}
```

---

## DAX Cluster

```hcl
resource "aws_dax_cluster" "main" {
  cluster_name       = "${var.project}-dax-${var.environment}"
  iam_role_arn       = aws_iam_role.dax.arn
  node_type          = "dax.r5.large"   # r5.large → r5.xlarge based on cache size needed
  replication_factor = 3  # 3 nodes across 3 AZs for HA

  subnet_group_name  = aws_dax_subnet_group.main.name
  security_group_ids = [aws_security_group.dax.id]

  server_side_encryption {
    enabled = true
  }

  # DAX cache TTL
  # item_ttl = 300  # 5 minutes default; configure per SDK
  # query_ttl = 300  # 5 minutes default

  tags = {
    Name        = "${var.project}-dax"
    Environment = var.environment
  }
}

resource "aws_dax_subnet_group" "main" {
  name       = "${var.project}-dax-subnet-group"
  subnet_ids = var.private_subnet_ids
}
```

**Application code change for DAX:**
```python
import amazon_dax_client  # Install: pip install amazon-dax-client

dax = amazon_dax_client.AmazonDaxClient(
    endpoints=['my-dax-cluster.xyz.dax-clusters.us-east-1.amazonaws.com:8111'],
    region_name='us-east-1'
)

# Use dax exactly like boto3 dynamodb
table = dax.Table('ecommerce')
response = table.get_item(Key={'PK': 'USER#123', 'SK': 'PROFILE'})
```

---

## DynamoDB Streams + Lambda

```hcl
resource "aws_lambda_event_source_mapping" "dynamodb_stream" {
  event_source_arn              = aws_dynamodb_table.ecommerce.stream_arn
  function_name                 = aws_lambda_function.stream_processor.arn
  starting_position             = "LATEST"
  batch_size                    = 100
  maximum_batching_window_in_seconds = 5
  parallelization_factor        = 2  # 2 concurrent Lambda per shard

  bisect_batch_on_function_error = true  # Bisect batch on error to identify bad record

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.stream_dlq.arn
    }
  }

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT", "MODIFY"]  # Only process inserts and updates
        dynamodb = {
          NewImage = {
            type = [{ "S" = "order" }]  # Only process order items
          }
        }
      })
    }
  }
}
```

---

## Key Design Patterns

### Composite Sort Key for Range Queries
```
# Query: Get all orders for user in date range
PK = "USER#123"
SK = "ORDER#2024-05-01#order-abc"  # Date prefix enables range queries

# DynamoDB query:
table.query(
    KeyConditionExpression=Key('PK').eq('USER#123') &
                           Key('SK').between('ORDER#2024-05-01', 'ORDER#2024-05-31')
)
```

### GSI Overloading (Sparse Index)
```
# Only some items have GSI keys — index is sparse
# Items without GSI1PK don't appear in GSI at all
# Use for status-based queries where only a fraction of items are "active"
```

### Write Sharding for Hot Partitions
```python
import random
SHARD_COUNT = 10

def get_shard_key(base_key):
    shard = random.randint(0, SHARD_COUNT - 1)
    return f"{base_key}#{shard}"

# Write to shard
pk = get_shard_key("LEADERBOARD#global")

# Read all shards (parallel reads)
import asyncio
async def read_all_shards(base_key):
    tasks = [read_shard(f"{base_key}#{i}") for i in range(SHARD_COUNT)]
    return await asyncio.gather(*tasks)
```

---

## Cost Implications

| Mode | Cost |
|------|------|
| On-demand reads | $0.25/1M RCUs |
| On-demand writes | $1.25/1M WCUs |
| Provisioned reads | $0.00013/RCU-hour |
| Provisioned writes | $0.00065/WCU-hour |
| Storage | $0.25/GB-month |
| DAX node (r5.large) | ~$158/month |
| Global tables replication | $0.105/WCU (replicated to each additional region) |
| Streams | $0.02/100k stream read requests |

**Rule of thumb:** On-demand if traffic is spiky or unpredictable. Provisioned + auto-scaling if traffic is steady (30-50% cheaper at scale).

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using status or boolean as partition key | Use high-cardinality keys (UUID, user ID) |
| Multi-table design for related entities | Single-table design with composite keys |
| GSI with ALL projection on large items | Use INCLUDE projection with only needed attributes |
| Not enabling PITR | Always enable point_in_time_recovery |
| Scanning table instead of querying | Never use Scan in production — design GSIs for all access patterns |
| No TTL on session/temporary data | Always use TTL for data with a natural expiry |
| Not stream_view_type = NEW_AND_OLD_IMAGES | Without old image, you can't compute deltas in stream processor |

---

## Verification Commands

```bash
# Table metadata
aws dynamodb describe-table \
  --table-name prod-ecommerce \
  --query 'Table.{Status:TableStatus,ItemCount:ItemCount,SizeBytes:TableSizeBytes,Stream:StreamSpecification}'

# Check consumed capacity
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name ConsumedReadCapacityUnits \
  --dimensions Name=TableName,Value=prod-ecommerce \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum

# Check for throttling
aws cloudwatch get-metric-statistics \
  --namespace AWS/DynamoDB \
  --metric-name UserErrors \
  --dimensions Name=TableName,Value=prod-ecommerce \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum

# Get item (for testing)
aws dynamodb get-item \
  --table-name prod-ecommerce \
  --key '{"PK":{"S":"USER#123"},"SK":{"S":"PROFILE"}}' \
  --return-consumed-capacity TOTAL
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
