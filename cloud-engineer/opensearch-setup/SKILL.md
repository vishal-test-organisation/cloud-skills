# OpenSearch Service Setup - Complete Skill Documentation

**name:** OpenSearch Service Setup

**description:** Deploy Amazon OpenSearch Service clusters for log analytics and full-text search with fine-grained access control, UltraWarm and Cold storage tiers, Index State Management (ISM) policies for automatic index lifecycle, Kibana/Dashboards integration, and VPC deployment with encryption.

---

## Your Expertise

Senior Search and Analytics Infrastructure Engineer with 12+ years deploying Elasticsearch and OpenSearch clusters for production log analytics and full-text search. AWS Solutions Architect Professional certified. Designed OpenSearch architectures ingesting billions of log events daily for security operations, application monitoring, and e-commerce search.

**Expert in:**
- Cluster sizing — hot/UltraWarm/Cold storage tiers, shard strategy, replica count
- Fine-grained access control (FGAC) — internal users, roles, role mapping, document-level security
- Index State Management — rollover policies, automatic shrink/force-merge, tier transitions
- Ingest pipelines — grok patterns, date parsing, field enrichment, index routing
- OpenSearch Dashboards — Kibana interface, saved searches, visualizations, alerting
- Cross-cluster replication — for disaster recovery and geo-distributed search
- VPC deployment — private cluster, proxy patterns for Dashboards access

OpenSearch is the right choice when you need full-text search, log aggregation with complex queries, or time-series analytics that CloudWatch Logs Insights cannot handle economically.

---

## Common Rules

**MANDATORY RULES FOR EVERY OPENSEARCH TASK:**

1. **ALWAYS DEPLOY IN VPC** — Public OpenSearch endpoints (even with FGAC) are exposed to internet scanners. VPC placement means the cluster is only reachable from within your network. Use a VPN or reverse proxy for Dashboards access.

2. **FINE-GRAINED ACCESS CONTROL IS MANDATORY** — Open access policies (`Allow *`) are the source of most OpenSearch data breaches. Enable FGAC with dedicated admin user. Application roles get only the minimum permissions (indices they write/read, no cluster admin).

3. **SHARD SIZING: 10-50 GB PER SHARD** — Undersized shards (< 1 GB) waste memory. Oversized shards (> 50 GB) cause slow queries and difficult rebalancing. Use rollover policies to keep shards in range. Log indices: 1 index per day with target shard size 20-30 GB.

4. **ISM POLICIES PREVENT DISK FULL** — Without Index State Management, old indices accumulate forever. Set up ISM to roll over at 30 GB or 1 day, transition to UltraWarm at 7 days, and delete at 90 days. A disk-full cluster is unrecoverable without data loss.

5. **DEDICATED MASTER NODES FOR CLUSTERS WITH 10+ DATA NODES** — Dedicated masters handle cluster state management separately from data nodes. Without them, data nodes spend resources on cluster management, causing instability under load.

6. **NO AI TOOL REFERENCES** — No mentions in ISM policies, FGAC role descriptions, or dashboard configurations. Output reads as infrastructure engineer work.

---

## Architecture: Storage Tiers

```
Hot Tier (SSD, high IOPS)
  └── Last 7 days of logs — active queries and ingestion
      │
      ▼ ISM Policy: rollover at 30GB or 1 day
UltraWarm Tier (S3-backed, warm cache)
  └── 7-30 days — queries available but slower
      │
      ▼ ISM Policy: transition at 7 days
Cold Tier (S3-backed, no cache)
  └── 30-90 days — infrequent access
      │
      ▼ ISM Policy: delete at 90 days
```

---

## Terraform: OpenSearch Domain

```hcl
resource "aws_opensearch_domain" "main" {
  domain_name    = "${var.project}-${var.environment}"
  engine_version = "OpenSearch_2.11"

  cluster_config {
    instance_type            = "r6g.large.search"  # Hot tier data nodes
    instance_count           = 3                    # 3 data nodes (1 per AZ)
    zone_awareness_enabled   = true
    zone_awareness_config {
      availability_zone_count = 3
    }

    dedicated_master_enabled = true                   # Dedicated masters for stability
    dedicated_master_type    = "m6g.large.search"
    dedicated_master_count   = 3                      # Always 3 dedicated masters

    warm_enabled = true
    warm_type    = "ultrawarm1.medium.search"
    warm_count   = 2

    cold_storage_options {
      enabled = true
    }
  }

  ebs_options {
    ebs_enabled = true
    volume_type = "gp3"
    volume_size = 100  # GB per data node
    iops        = 3000
    throughput  = 125
  }

  vpc_options {
    subnet_ids         = slice(var.private_subnet_ids, 0, 3)  # One subnet per AZ
    security_group_ids = [aws_security_group.opensearch.id]
  }

  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  encrypt_at_rest {
    enabled    = true
    kms_key_id = aws_kms_key.opensearch.arn
  }

  node_to_node_encryption {
    enabled = true
  }

  advanced_security_options {
    enabled                        = true
    anonymous_auth_enabled         = false
    internal_user_database_enabled = true
    master_user_options {
      master_user_name     = var.opensearch_master_user
      master_user_password = var.opensearch_master_password
    }
  }

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { AWS = "*" }
      Action    = "es:*"
      Resource  = "arn:aws:es:${var.region}:${var.account_id}:domain/${var.project}-${var.environment}/*"
      Condition = {
        IpAddress = {
          "aws:SourceIp" = var.allowed_cidr_blocks  # VPC CIDRs
        }
      }
    }]
  })

  log_publishing_options {
    log_type                 = "INDEX_SLOW_LOGS"
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_slow.arn
    enabled                  = true
  }

  log_publishing_options {
    log_type                 = "SEARCH_SLOW_LOGS"
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_slow.arn
    enabled                  = true
  }

  log_publishing_options {
    log_type                 = "ES_APPLICATION_LOGS"
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_app.arn
    enabled                  = true
  }

  tags = {
    Name        = "${var.project}-opensearch-${var.environment}"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## Index State Management Policy

```json
{
  "policy": {
    "description": "Log index lifecycle: rollover → UltraWarm → Cold → Delete",
    "default_state": "hot",
    "states": [
      {
        "name": "hot",
        "actions": [
          {
            "rollover": {
              "min_index_age": "1d",
              "min_size": "30gb",
              "min_doc_count": 1000000
            }
          }
        ],
        "transitions": [
          {
            "state_name": "warm",
            "conditions": { "min_rollover_age": "7d" }
          }
        ]
      },
      {
        "name": "warm",
        "actions": [
          {
            "warm_migration": {}
          },
          {
            "replica_count": { "number_of_replicas": 0 }
          }
        ],
        "transitions": [
          {
            "state_name": "cold",
            "conditions": { "min_index_age": "30d" }
          }
        ]
      },
      {
        "name": "cold",
        "actions": [
          {
            "cold_migration": { "timestamp_field": "@timestamp" }
          }
        ],
        "transitions": [
          {
            "state_name": "delete",
            "conditions": { "min_index_age": "90d" }
          }
        ]
      },
      {
        "name": "delete",
        "actions": [{ "delete": {} }],
        "transitions": []
      }
    ],
    "ism_template": [
      {
        "index_patterns": ["app-logs-*", "vpc-flow-*", "waf-logs-*"],
        "priority": 100
      }
    ]
  }
}
```

---

## Fine-Grained Access Control Roles

```json
// Ingest role — write-only for application log shippers
{
  "cluster_permissions": ["cluster:monitor/main", "cluster:monitor/nodes/info"],
  "index_permissions": [
    {
      "index_patterns": ["app-logs-*"],
      "allowed_actions": ["indices:admin/create", "indices:data/write/*", "indices:admin/mapping/put"]
    }
  ]
}

// Read role — Kibana users (Developers)
{
  "cluster_permissions": ["cluster:monitor/health", "cluster:monitor/state"],
  "index_permissions": [
    {
      "index_patterns": ["app-logs-*"],
      "allowed_actions": ["indices:data/read/*", "indices:admin/mappings/get", "indices:admin/get"]
    }
  ],
  "tenant_permissions": [
    {
      "tenant_patterns": ["global_tenant"],
      "allowed_actions": ["kibana:saved_objects/_search", "kibana:saved_objects/index-pattern/*"]
    }
  ]
}
```

---

## Log Ingestion with Kinesis Firehose

```hcl
resource "aws_kinesis_firehose_delivery_stream" "to_opensearch" {
  name        = "${var.project}-logs-to-opensearch"
  destination = "opensearch"

  opensearch_configuration {
    domain_arn = aws_opensearch_domain.main.arn
    role_arn   = aws_iam_role.firehose_opensearch.arn
    index_name = "app-logs"
    index_rotation_period = "OneDay"  # Creates app-logs-YYYY-MM-DD indices

    buffering_interval = 60
    buffering_size     = 5  # MB

    s3_backup_mode = "FailedDocumentsOnly"
    s3_configuration {
      role_arn           = aws_iam_role.firehose_opensearch.arn
      bucket_arn         = aws_s3_bucket.failed_logs.arn
      compression_format = "GZIP"
    }

    processing_configuration {
      enabled = true
      processors {
        type = "Lambda"
        parameters {
          parameter_name  = "LambdaArn"
          parameter_value = aws_lambda_function.log_transform.arn
        }
      }
    }

    vpc_config {
      subnet_ids         = slice(var.private_subnet_ids, 0, 2)
      security_group_ids = [aws_security_group.firehose.id]
      role_arn           = aws_iam_role.firehose_opensearch.arn
    }
  }
}
```

---

## Security Group

```hcl
resource "aws_security_group" "opensearch" {
  name        = "${var.project}-opensearch"
  description = "OpenSearch — allow HTTPS from VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "HTTPS from application tier"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}
```

---

## Cost Implications

| Resource | Monthly Cost (us-east-1) |
|----------|------------------------|
| r6g.large.search data node | ~$105 |
| m6g.large.search master node | ~$70 |
| UltraWarm medium (warm tier) | ~$105 |
| Cold storage | $0.01/GB/month |
| SSD storage (gp3) | $0.135/GB/month |

**3-node r6g.large cluster:** ~$315 data + $210 masters = ~$525/month

**Optimization:**
- UltraWarm for 7-30 day data saves 90% vs hot SSD
- Cold tier for 30-90 day saves 99% vs hot SSD
- Set replica_count = 0 on UltraWarm/Cold (replicated in S3 already)
- Use 1-year Reserved pricing for 30-40% discount

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Public endpoint without FGAC | Always VPC + fine-grained access control |
| No ISM policy | Set up ISM on day 1 — disk fills up fast with logs |
| Too many small shards | Target 20-30 GB per shard; use rollover policies |
| `Allow *` access policy | Restrict by VPC CIDR at minimum; use FGAC roles |
| No dedicated masters at scale | Add 3 dedicated masters for clusters with 10+ data nodes |
| Not using UltraWarm for old data | 80% cost saving for data older than 7 days |
| Ingesting without transform | Parse timestamp and extract fields before indexing |

---

## Verification Commands

```bash
# Check cluster health
curl -u admin:password https://<opensearch-endpoint>/_cluster/health?pretty

# List indices with sizes
curl -u admin:password "https://<endpoint>/_cat/indices?v&h=index,docs.count,store.size,pri.store.size&s=store.size:desc"

# Check ISM policy status
curl -u admin:password "https://<endpoint>/_plugins/_ism/explain/app-logs-*?pretty"

# Shard allocation
curl -u admin:password "https://<endpoint>/_cat/shards?v&h=index,shard,prirep,state,node"

# Search latency stats
aws cloudwatch get-metric-statistics \
  --namespace AWS/ES \
  --metric-name SearchLatency \
  --dimensions Name=DomainName,Value=prod-opensearch Name=ClientId,Value=<account-id> \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics p99
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
