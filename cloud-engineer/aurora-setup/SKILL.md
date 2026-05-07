# Aurora Setup - Complete Skill Documentation

**name:** Aurora Setup

**description:** Deploy Amazon Aurora clusters with MySQL and PostgreSQL compatibility, configure auto-scaling read replicas, Aurora Global Database for multi-region DR, Aurora Serverless v2 for variable workloads, and failover testing procedures with full observability.

---

## Your Expertise

Senior Database Infrastructure Engineer with 12+ years running Aurora clusters in production. AWS Database Specialty and Solutions Architect Professional certified. Migrated large-scale RDS workloads to Aurora, achieving 3-5x performance improvements. Designed Aurora Global Database topologies for financial platforms requiring sub-second cross-region failover.

**Expert in:**
- Aurora architecture — cluster volume, writer/reader instances, automatic storage growth
- Aurora MySQL vs PostgreSQL — version selection, feature differences, migration paths
- Serverless v2 — ACU scaling, minimum/maximum capacity, instant scaling
- Global Database — primary cluster, secondary regions, RPO ~1 second, sub-1-minute RTO
- Auto-scaling read replicas — CloudWatch metric targets, scale-in/scale-out policies
- Failover — planned switchover vs unplanned failover, promotion priority, failover events
- Aurora Backtrack — rewind database without restore (MySQL only)
- Performance Insights, Enhanced Monitoring, Database Activity Streams

Aurora delivers MySQL/PostgreSQL compatibility with enterprise-grade availability, performance, and storage engine. Always the right choice over standard RDS for production workloads at scale.

---

## Common Rules

**MANDATORY RULES FOR EVERY AURORA TASK:**

1. **CLUSTER ≠ INSTANCE** — Aurora separates the cluster (shared storage) from instances (compute). Creating a cluster with no instances means zero compute. Always provision at least one writer instance. Add reader instances for read scaling.

2. **AURORA SERVERLESS V2 FOR VARIABLE WORKLOADS** — If your traffic varies 10x between peak and trough, Serverless v2 eliminates over-provisioning. It scales in ACU (Aurora Capacity Units) increments in ~seconds. Set minimum ACU ≥ 0.5 (not 0 — 0 causes cold starts).

3. **READER ENDPOINT IS FOR READ TRAFFIC ONLY** — The cluster reader endpoint load-balances across all reader instances. Application must use two connection strings: writer endpoint for writes, reader endpoint for reads. Applications ignoring this route all reads to the writer.

4. **GLOBAL DATABASE FAILOVER IS A TWO-STEP OPERATION** — Failover requires first promoting the secondary region cluster (detaches from global DB) then reconfiguring applications. Plan this procedure and test it annually.

5. **STORAGE AUTOSCALES AUTOMATICALLY — CANNOT SHRINK** — Aurora storage grows automatically from 10 GB to 128 TB in 10 GB increments. It cannot shrink. Monitor `FreeLocalStorage` not `FreeStorageSpace`. Plan for growth.

6. **NO AI TOOL REFERENCES** — No mentions in cluster configurations, parameter groups, or auto-scaling policies. Output reads as database engineer work.

---

## Architecture Overview

```
Aurora Cluster
├── Cluster Endpoint (writer) → Writer Instance (db.r6g.large)
├── Reader Endpoint (load-balanced) → Reader Instance 1
│                                   → Reader Instance 2
└── Shared Cluster Volume (auto-scaling, 6 copies across 3 AZs)

Global Database
├── Primary Cluster (us-east-1) — all reads + writes
└── Secondary Cluster (us-west-2) — reads only, RPO ~1s
```

---

## Terraform: Aurora PostgreSQL Cluster

```hcl
resource "aws_rds_cluster" "main" {
  cluster_identifier = "${var.project}-${var.environment}-aurora"

  engine         = "aurora-postgresql"
  engine_version = "16.3"
  engine_mode    = "provisioned"

  database_name   = var.database_name
  master_username = var.master_username
  manage_master_user_password = true  # Secrets Manager managed
  master_user_secret_kms_key_id = aws_kms_key.rds.arn

  db_subnet_group_name            = aws_db_subnet_group.main.name
  vpc_security_group_ids          = [aws_security_group.aurora.id]
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.main.name

  storage_encrypted = true
  kms_key_id        = aws_kms_key.rds.arn

  backup_retention_period      = 30
  preferred_backup_window      = "02:00-03:00"
  preferred_maintenance_window = "Mon:04:00-Mon:05:00"

  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-${var.environment}-final"
  copy_tags_to_snapshot     = true

  deletion_protection             = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  iam_database_authentication_enabled = true

  serverlessv2_scaling_configuration {
    min_capacity = 0.5   # Minimum ACU (never 0 for production)
    max_capacity = 64    # Maximum ACU (64 ACU = ~128 vCPU equivalent)
  }

  tags = {
    Name        = "${var.project}-${var.environment}-aurora"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Writer instance
resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${var.project}-${var.environment}-writer"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverlessv2"  # For Serverless v2
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  publicly_accessible            = false
  db_parameter_group_name        = aws_db_parameter_group.aurora_pg.name
  monitoring_interval            = 60
  monitoring_role_arn            = aws_iam_role.rds_enhanced_monitoring.arn
  performance_insights_enabled   = true
  performance_insights_retention_period = 7
  performance_insights_kms_key_id = aws_kms_key.rds.arn
  auto_minor_version_upgrade     = true
  promotion_tier                 = 0  # Priority 0 = first promoted on failover

  tags = {
    Name = "${var.project}-${var.environment}-aurora-writer"
    Role = "writer"
  }
}

# Reader instances
resource "aws_rds_cluster_instance" "readers" {
  count              = var.reader_count  # e.g., 2
  identifier         = "${var.project}-${var.environment}-reader-${count.index + 1}"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverlessv2"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  publicly_accessible          = false
  db_parameter_group_name      = aws_db_parameter_group.aurora_pg.name
  monitoring_interval          = 60
  monitoring_role_arn          = aws_iam_role.rds_enhanced_monitoring.arn
  performance_insights_enabled = true
  promotion_tier               = count.index + 1  # Higher tier = lower priority for failover

  tags = {
    Name = "${var.project}-${var.environment}-aurora-reader-${count.index + 1}"
    Role = "reader"
  }
}
```

---

## Read Replica Auto-Scaling

```hcl
resource "aws_appautoscaling_target" "aurora_readers" {
  max_capacity       = 10
  min_capacity       = 1
  resource_id        = "cluster:${aws_rds_cluster.main.cluster_identifier}"
  scalable_dimension = "rds:cluster:ReadReplicaCount"
  service_namespace  = "rds"
}

resource "aws_appautoscaling_policy" "aurora_readers_cpu" {
  name               = "${var.project}-aurora-reader-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.aurora_readers.resource_id
  scalable_dimension = aws_appautoscaling_target.aurora_readers.scalable_dimension
  service_namespace  = aws_appautoscaling_target.aurora_readers.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "RDSReaderAverageCPUUtilization"
    }
    target_value       = 70.0   # Scale when avg CPU > 70%
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

resource "aws_appautoscaling_policy" "aurora_readers_connections" {
  name               = "${var.project}-aurora-reader-connection-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.aurora_readers.resource_id
  scalable_dimension = aws_appautoscaling_target.aurora_readers.scalable_dimension
  service_namespace  = aws_appautoscaling_target.aurora_readers.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "RDSReaderAverageDatabaseConnections"
    }
    target_value       = 500
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}
```

---

## Aurora Global Database

```hcl
# Primary cluster (us-east-1)
resource "aws_rds_global_cluster" "main" {
  global_cluster_identifier = "${var.project}-global"
  engine                    = "aurora-postgresql"
  engine_version            = "16.3"
  storage_encrypted         = true
}

resource "aws_rds_cluster" "primary" {
  cluster_identifier        = "${var.project}-primary"
  global_cluster_identifier = aws_rds_global_cluster.main.id
  engine                    = "aurora-postgresql"
  engine_version            = "16.3"
  # ... other config
}

# Secondary cluster (us-west-2) — for reads and DR
resource "aws_rds_cluster" "secondary" {
  provider                  = aws.us_west_2
  cluster_identifier        = "${var.project}-secondary"
  global_cluster_identifier = aws_rds_global_cluster.main.id
  engine                    = "aurora-postgresql"
  engine_version            = "16.3"
  # Note: No master_username/password on secondary — inherited from global cluster
  # ... other config
}
```

---

## Cluster Parameter Group

```hcl
resource "aws_rds_cluster_parameter_group" "main" {
  name   = "${var.project}-aurora-pg16"
  family = "aurora-postgresql16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"
  }
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements,pg_hint_plan"
    apply_method = "pending-reboot"
  }
  parameter {
    name  = "rds.force_ssl"
    value = "1"  # Require SSL connections
  }
  parameter {
    name  = "log_connections"
    value = "1"
  }
}
```

---

## Failover Testing

```bash
# Simulate planned failover (controlled switchover — minimal downtime)
aws rds failover-db-cluster \
  --db-cluster-identifier prod-aurora \
  --target-db-instance-identifier prod-aurora-reader-1

# Monitor failover event
aws rds describe-events \
  --source-identifier prod-aurora \
  --source-type db-cluster \
  --duration 60 \
  --query 'Events[*].{Time:Date,Message:Message}'

# Verify new writer
aws rds describe-db-cluster-endpoints \
  --db-cluster-identifier prod-aurora \
  --query 'DBClusterEndpoints[*].{Type:EndpointType,Endpoint:Endpoint,Status:Status}'
```

---

## Cost Implications

| Resource | Cost (us-east-1) |
|----------|-----------------|
| Aurora Serverless v2 ACU | $0.12/ACU-hour |
| Aurora I/O-Optimized storage | $0.225/GB-month (includes I/O) |
| Aurora Standard storage | $0.10/GB-month + $0.20/1M I/O requests |
| Global Database (replication) | $0.20/1M replicated write I/Os |
| Backtrack storage | $0.021/GB-hour |
| Enhanced Monitoring | Free (CloudWatch Logs standard rates) |

**Serverless v2 example:** 2 ACU minimum, 16 ACU maximum = $0.24/hr idle to $1.92/hr at peak.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Sending all queries to writer endpoint | Use reader endpoint for SELECT queries |
| Serverless v2 min_capacity = 0 | Set min 0.5 ACU — 0 causes cold start delays |
| Not testing failover | Run `failover-db-cluster` quarterly in staging |
| Forgetting cluster vs instance parameter groups | Cluster PG applies to engine; instance PG applies to individual instance |
| No auto-scaling on reader replicas | Add AppAutoScaling policy for CPU/connection targets |
| Global Database failover not documented | Write and test the failover runbook before you need it |

---

## Verification Commands

```bash
# Cluster status and endpoints
aws rds describe-db-clusters \
  --db-cluster-identifier prod-aurora \
  --query 'DBClusters[0].{Status:Status,Engine:Engine,StorageEncrypted:StorageEncrypted,MultiAZ:MultiAZ,ReaderEndpoint:ReaderEndpoint}'

# List cluster instances and their roles
aws rds describe-db-instances \
  --filters Name=db-cluster-id,Values=prod-aurora \
  --query 'DBInstances[*].{ID:DBInstanceIdentifier,Role:IAMDatabaseAuthenticationEnabled,Class:DBInstanceClass,Status:DBInstanceStatus}'

# Check Performance Insights
aws pi get-resource-metrics \
  --service-type RDS \
  --identifier db-XXXXXXXXXX \
  --metric-queries '[{"Metric":"db.load.avg","GroupBy":{"Group":"db.wait_event"}}]' \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period-in-seconds 60
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
