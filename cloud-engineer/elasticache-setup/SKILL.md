# ElastiCache Setup - Complete Skill Documentation

**name:** ElastiCache Setup

**description:** Deploy Amazon ElastiCache Redis clusters with replication groups, Multi-AZ failover, Cluster Mode for horizontal sharding, TLS in-transit and at-rest encryption, eviction policies, and connection management for high-throughput caching and session storage workloads.

---

## Your Expertise

Senior Caching Infrastructure Engineer with 12+ years deploying ElastiCache Redis clusters for production web applications. AWS Solutions Architect Professional and Database Specialty certified. Designed Redis architectures handling 1M+ operations/second with sub-millisecond latency, zero data loss on instance failures, and 99.99% cluster availability.

**Expert in:**
- Redis replication groups — primary/replica topology, automatic failover, Multi-AZ
- Cluster Mode — sharding across multiple node groups, hash slots, cross-slot operations
- ElastiCache Serverless — automatic capacity management, pay-per-use for unpredictable workloads
- Eviction policies — allkeys-lru, volatile-lru, allkeys-lfu, noeviction — choosing by use case
- TLS in-transit — encrypted connections, certificate validation, client config
- AUTH and RBAC — Redis AUTH token, Redis 7 ACL (Access Control Lists)
- Data persistence — AOF, RDB snapshots — tradeoffs for cache vs persistent store
- Connection management — connection pools, pipeline batching, Cluster Mode client routing

The right Redis architecture eliminates database bottlenecks, reduces response times by 10-100x, and handles traffic spikes the database cannot absorb.

---

## Common Rules

**MANDATORY RULES FOR EVERY ELASTICACHE TASK:**

1. **MULTI-AZ WITH AUTO-FAILOVER FOR PRODUCTION** — Single-node Redis has no failover. Enable `automatic_failover_enabled = true` with at least one replica per node group. Failover completes in 30-60 seconds.

2. **TLS EVERYWHERE — NO PLAINTEXT CONNECTIONS** — Set `transit_encryption_enabled = true`. Applications must connect with TLS. Redis without TLS exposes session data, tokens, and cached PII in plaintext to anyone on the same network segment.

3. **CHOOSE EVICTION POLICY BEFORE DATA GROWS** — The default `noeviction` causes writes to fail when memory is full. For cache workloads set `maxmemory-policy = allkeys-lru`. For mixed cache+persistent workloads set `volatile-lru`. Never use `noeviction` for cache-only clusters.

4. **CLUSTER MODE FOR SCALING BEYOND 255 GB** — Single-shard Redis maxes out at the largest node type (~220 GB for r6g.16xlarge). For datasets larger than that, enable Cluster Mode. Note: Cluster Mode restricts multi-key operations to the same hash slot.

5. **SIZE BASED ON DATA + OVERHEAD** — Redis stores data in-memory with 20-30% overhead for internal structures. If your dataset is 10 GB, provision 14-16 GB nodes. Monitor `FreeableMemory` and alarm at 20% free.

6. **NO AI TOOL REFERENCES** — No mentions in parameter group configs, Terraform comments, or monitoring alerts. Output reads as infrastructure engineer work.

---

## Topology Selection

| Topology | Use Case | Max Memory | Failover |
|----------|----------|------------|----------|
| Single node | Dev/test only | Node max | None |
| Replication group (no cluster) | < 220 GB, simple client | Node max | Yes (replica) |
| Cluster Mode enabled | > 220 GB or > 1M ops/sec | Unlimited (shards * node) | Yes per shard |
| ElastiCache Serverless | Unpredictable workload | Auto-scales | Built-in |

---

## Terraform: Redis Replication Group (Non-Cluster Mode)

```hcl
resource "aws_elasticache_replication_group" "main" {
  replication_group_id = "${var.project}-redis-${var.environment}"
  description          = "Redis cache for ${var.project} ${var.environment}"

  node_type               = var.cache_node_type  # e.g., cache.r6g.large
  num_cache_clusters      = 3  # 1 primary + 2 replicas
  automatic_failover_enabled = true
  multi_az_enabled        = true

  engine               = "redis"
  engine_version       = "7.1"
  parameter_group_name = aws_elasticache_parameter_group.main.name
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  # Security
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.elasticache.arn
  auth_token                 = var.redis_auth_token  # Min 16 chars

  # Snapshots
  snapshot_retention_limit = 7
  snapshot_window          = "03:00-04:00"

  maintenance_window   = "Mon:04:00-Mon:05:00"
  apply_immediately    = false

  auto_minor_version_upgrade = true
  notification_topic_arn     = aws_sns_topic.alerts.arn

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis_slow_log.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "slow-log"
  }

  log_delivery_configuration {
    destination      = aws_cloudwatch_log_group.redis_engine_log.name
    destination_type = "cloudwatch-logs"
    log_format       = "json"
    log_type         = "engine-log"
  }

  tags = {
    Name        = "${var.project}-redis-${var.environment}"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## Terraform: Redis Cluster Mode

```hcl
resource "aws_elasticache_replication_group" "cluster" {
  replication_group_id       = "${var.project}-redis-cluster-${var.environment}"
  description                = "Redis Cluster Mode for ${var.project}"

  node_type                  = "cache.r6g.xlarge"
  num_node_groups            = 6    # 6 shards
  replicas_per_node_group    = 2    # 2 replicas per shard
  automatic_failover_enabled = true
  multi_az_enabled           = true

  engine               = "redis"
  engine_version       = "7.1"
  parameter_group_name = aws_elasticache_parameter_group.cluster.name
  port                 = 6379

  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.redis.id]

  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  kms_key_id                 = aws_kms_key.elasticache.arn
  auth_token                 = var.redis_auth_token

  snapshot_retention_limit = 7
  snapshot_window          = "03:00-04:00"
}
```

---

## Terraform: Parameter Group

```hcl
resource "aws_elasticache_parameter_group" "main" {
  name   = "${var.project}-redis7"
  family = "redis7"

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"  # Evict LRU keys when memory full (cache use case)
  }

  parameter {
    name  = "activedefrag"
    value = "yes"  # Active memory defragmentation
  }

  parameter {
    name  = "lazyfree-lazy-eviction"
    value = "yes"  # Async eviction to avoid blocking
  }

  parameter {
    name  = "slowlog-log-slower-than"
    value = "10000"  # Log commands slower than 10ms (10000 microseconds)
  }

  parameter {
    name  = "slowlog-max-len"
    value = "128"
  }

  parameter {
    name  = "tcp-keepalive"
    value = "300"
  }

  parameter {
    name  = "timeout"
    value = "300"  # Close idle connections after 300 seconds
  }
}

# Cluster mode parameter group
resource "aws_elasticache_parameter_group" "cluster" {
  name   = "${var.project}-redis7-cluster"
  family = "redis7.cluster.on"  # Note: cluster.on suffix for Cluster Mode

  parameter {
    name  = "maxmemory-policy"
    value = "allkeys-lru"
  }
  parameter {
    name  = "cluster-enabled"
    value = "yes"
  }
}
```

---

## Terraform: Subnet Group and Security Group

```hcl
resource "aws_elasticache_subnet_group" "main" {
  name       = "${var.project}-redis-subnet-group"
  subnet_ids = var.private_subnet_ids  # Private subnets, no public IPs on cache nodes

  tags = { Name = "${var.project}-redis-subnet-group" }
}

resource "aws_security_group" "redis" {
  name        = "${var.project}-${var.environment}-redis"
  description = "ElastiCache Redis — allow from app tier only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from application tier"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

---

## ElastiCache Serverless

```hcl
resource "aws_elasticache_serverless_cache" "main" {
  engine = "redis"
  name   = "${var.project}-serverless-${var.environment}"

  cache_usage_limits {
    data_storage {
      maximum = 100  # GB
      unit    = "GB"
    }
    ecpu_per_second {
      maximum = 50000  # ECPUs per second
    }
  }

  daily_snapshot_time      = "03:00"
  description              = "Serverless Redis for ${var.project}"
  kms_key_id               = aws_kms_key.elasticache.arn
  major_engine_version     = "7"
  snapshot_retention_limit = 7

  security_group_ids = [aws_security_group.redis.id]
  subnet_ids         = var.private_subnet_ids
}
```

---

## Connection Patterns (Python)

```python
import redis
from redis.cluster import RedisCluster

# Non-cluster mode
r = redis.Redis(
    host=os.environ['REDIS_HOST'],  # Primary endpoint
    port=6379,
    password=os.environ['REDIS_AUTH_TOKEN'],
    ssl=True,
    ssl_certfile=None,  # ElastiCache self-signed — disable cert verification or bundle CA
    ssl_cert_reqs=None,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    retry_on_timeout=True,
    max_connections=50,  # Pool size per process
    health_check_interval=30
)

# Cluster mode
rc = RedisCluster(
    host=os.environ['REDIS_CLUSTER_HOST'],  # Configuration endpoint
    port=6379,
    password=os.environ['REDIS_AUTH_TOKEN'],
    ssl=True,
    ssl_cert_reqs=None,
    decode_responses=True,
    skip_full_coverage_check=True,  # Required for ElastiCache
)

# Pipeline for batching commands
pipe = r.pipeline(transaction=False)
pipe.set('key1', 'value1', ex=3600)
pipe.set('key2', 'value2', ex=3600)
pipe.get('key1')
results = pipe.execute()
```

---

## Eviction Policy Guide

| Policy | Behavior | Use Case |
|--------|----------|----------|
| `allkeys-lru` | Evict least recently used from ALL keys | Pure cache (recommended) |
| `volatile-lru` | Evict LRU from keys with TTL set | Mixed cache + persistent |
| `allkeys-lfu` | Evict least frequently used | Cache with unequal access patterns |
| `volatile-ttl` | Evict keys with shortest TTL first | Session storage |
| `noeviction` | Error on writes when full | Persistent data store ONLY |
| `allkeys-random` | Evict random key | Not recommended |

---

## CloudWatch Alarms

```hcl
resource "aws_cloudwatch_metric_alarm" "redis_memory" {
  alarm_name          = "${var.project}-redis-high-memory"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "FreeableMemory"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Average"
  threshold           = 536870912  # 512 MB in bytes
  alarm_actions       = [aws_sns_topic.alerts.arn]
  dimensions = {
    CacheClusterId = aws_elasticache_replication_group.main.id
  }
}

resource "aws_cloudwatch_metric_alarm" "redis_evictions" {
  alarm_name          = "${var.project}-redis-high-evictions"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "Evictions"
  namespace           = "AWS/ElastiCache"
  period              = 300
  statistic           = "Sum"
  threshold           = 1000
  alarm_actions       = [aws_sns_topic.alerts.arn]
  dimensions = {
    CacheClusterId = aws_elasticache_replication_group.main.id
  }
}
```

---

## Cost Implications

| Node Type | Memory | vCPU | Monthly Cost |
|-----------|--------|------|-------------|
| cache.t3.micro | 0.5 GB | 2 | ~$12 |
| cache.r6g.large | 13 GB | 2 | ~$113 |
| cache.r6g.xlarge | 26 GB | 4 | ~$226 |
| cache.r6g.2xlarge | 52 GB | 8 | ~$452 |

- Replicas add the same cost per node
- Multi-AZ does not add cost beyond the replica nodes
- Serverless: $0.00034/ECPU + $0.125/GB-hour stored

**Reserved nodes** (1-year): 30-35% discount over on-demand.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `maxmemory-policy = noeviction` for cache | Use allkeys-lru for cache workloads |
| Single-node in production | Always 1 primary + 2 replicas with Multi-AZ |
| No TLS | Set transit_encryption_enabled = true |
| Not setting connection pool size | Default pool is too small — set max_connections in client |
| Storing large objects (> 100 KB) | Redis is optimized for small objects; large values hurt throughput |
| Not monitoring evictions | Set alarm on Evictions metric — indicates memory pressure |
| Cluster Mode client connecting to primary endpoint | Cluster Mode requires Cluster-aware client and configuration endpoint |

---

## Verification Commands

```bash
# Cluster status
aws elasticache describe-replication-groups \
  --replication-group-id prod-redis \
  --query 'ReplicationGroups[0].{Status:Status,MultiAZ:MultiAZ,AutoFailover:AutomaticFailover,NodeGroups:NodeGroups[*].NodeGroupMembers[*].CurrentRole}'

# Test Redis connection (from EC2 in VPC)
redis-cli -h <primary-endpoint> -p 6379 -a <auth-token> --tls PING
redis-cli -h <primary-endpoint> -p 6379 -a <auth-token> --tls INFO memory | grep used_memory_human

# Check slow log
redis-cli -h <primary-endpoint> -a <auth-token> --tls SLOWLOG GET 10

# Memory usage stats
redis-cli -h <primary-endpoint> -a <auth-token> --tls MEMORY STATS

# Failover test
aws elasticache test-failover \
  --replication-group-id prod-redis \
  --node-group-id 0001
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
