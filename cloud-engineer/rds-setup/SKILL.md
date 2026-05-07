# RDS Setup - Complete Skill Documentation

**name:** RDS Setup

**description:** Deploy production-grade Amazon RDS instances for MySQL and PostgreSQL with Multi-AZ high availability, custom subnet groups, parameter groups, automated backups, Performance Insights, encryption at rest with KMS, IAM database authentication, and enhanced monitoring.

---

## Your Expertise

Senior Database and Cloud Infrastructure Engineer with 12+ years running relational databases on AWS RDS. AWS Database Specialty and Solutions Architect Professional certified. Managed hundreds of RDS instances across production workloads handling millions of transactions per day — zero data loss incidents, sub-second failover on Multi-AZ, and 99.99% availability.

**Expert in:**
- RDS engine selection — MySQL 8.0, PostgreSQL 15/16, version upgrade planning
- Multi-AZ deployment — synchronous replication, automatic failover, standby instance management
- Parameter groups — engine-specific tuning for OLTP vs analytics workloads
- Subnet groups and network isolation — private subnet placement, Security Group design
- Automated backups — retention windows, PITR (Point-in-Time Recovery), cross-region backup replication
- Read replicas — asynchronous replication, promotion procedure, cross-region replicas
- Performance Insights — SQL-level analysis, wait events, top SQL, database load visualization
- Storage — gp3 vs io1/io2 IOPS provisioning, storage autoscaling, encryption

Zero-downtime RDS deployments: encrypted, multi-AZ, private subnet, automated backups with tested restore procedures, and monitoring from day one.

---

## Common Rules

**MANDATORY RULES FOR EVERY RDS TASK:**

1. **MULTI-AZ FOR EVERY PRODUCTION DATABASE** — Single-AZ RDS has no automatic failover. An AZ outage means your database is down until AWS resolves it. Multi-AZ adds synchronous standby in a second AZ with 60-120 second automated failover.

2. **PRIVATE SUBNETS ONLY — NO PUBLIC ACCESSIBILITY** — Set `publicly_accessible = false`. Databases must never have public IPs. Access goes through application servers or bastion hosts within the VPC. A publicly accessible RDS with weak passwords is instant compromise.

3. **ENCRYPTION AT REST WITH KMS CMK** — Never use unencrypted RDS. Use a customer-managed KMS key, not the default `aws/rds` key. CMK enables cross-account sharing, custom key policies, and access auditing.

4. **PARAMETER GROUPS ARE NOT OPTIONAL** — The default parameter group is shared and cannot be modified. Create a custom parameter group for every RDS instance. This is where you set critical parameters: `max_connections`, `slow_query_log`, `log_bin_trust_function_creators`, etc.

5. **TEST YOUR BACKUP RESTORE PROCEDURE** — Automated backups mean nothing if you've never tested restoration. Run a PITR restore to a test instance quarterly. Document the RTO. Discover problems during drills, not real incidents.

6. **NO AI TOOL REFERENCES** — No mentions in parameter group descriptions, Terraform comments, or monitoring Lambda functions. Output reads as database engineer work.

---

## Engine Selection Guide

| Workload | Recommended Engine | Version |
|----------|-------------------|---------|
| General web application | MySQL | 8.0.x (latest) |
| Complex queries, JSONB | PostgreSQL | 16.x (latest) |
| High write throughput | PostgreSQL | 16.x |
| Legacy MySQL apps | MySQL | 8.0 (avoid 5.7 — EOL) |
| PostGIS/geospatial | PostgreSQL | 15+ |
| Analytics + OLTP mix | Aurora PostgreSQL | Latest |

---

## Terraform: MySQL RDS

```hcl
resource "aws_db_instance" "main" {
  identifier = "${var.project}-${var.environment}-mysql"

  engine         = "mysql"
  engine_version = "8.0.35"
  instance_class = var.db_instance_class  # e.g., db.t3.medium, db.r6g.large

  # Storage
  allocated_storage     = 100
  max_allocated_storage = 500  # Storage autoscaling up to 500 GB
  storage_type          = "gp3"
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  # Credentials
  db_name  = var.database_name
  username = var.master_username
  password = var.master_password  # Use random_password + Secrets Manager in practice
  # Alternatively use manage_master_user_password = true (Secrets Manager managed)

  # Network
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false

  # High Availability
  multi_az = true

  # Parameter and option groups
  parameter_group_name = aws_db_parameter_group.mysql.name
  option_group_name    = aws_db_option_group.mysql.name

  # Backups
  backup_retention_period   = 30  # Days (7 minimum, 30 for prod)
  backup_window             = "03:00-04:00"  # UTC
  delete_automated_backups  = false
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-${var.environment}-final-snapshot"
  copy_tags_to_snapshot     = true

  # Maintenance
  maintenance_window         = "Mon:04:00-Mon:05:00"
  auto_minor_version_upgrade = true

  # Monitoring
  monitoring_interval             = 60  # Enhanced monitoring every 60 seconds
  monitoring_role_arn             = aws_iam_role.rds_enhanced_monitoring.arn
  performance_insights_enabled    = true
  performance_insights_retention_period = 7  # Days (7 free, 731 paid)
  performance_insights_kms_key_id = aws_kms_key.rds.arn
  enabled_cloudwatch_logs_exports = ["general", "error", "slowquery"]

  # Deletion protection
  deletion_protection = true

  tags = {
    Name        = "${var.project}-${var.environment}-mysql"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## Terraform: PostgreSQL RDS

```hcl
resource "aws_db_instance" "postgres" {
  identifier = "${var.project}-${var.environment}-postgres"

  engine         = "postgres"
  engine_version = "16.3"
  instance_class = var.db_instance_class

  allocated_storage     = 100
  max_allocated_storage = 1000
  storage_type          = "gp3"
  iops                  = 3000   # Only needed if gp3 baseline 3000 IOPS is insufficient
  storage_encrypted     = true
  kms_key_id            = aws_kms_key.rds.arn

  db_name  = var.database_name
  username = var.master_username
  manage_master_user_password = true  # AWS manages in Secrets Manager
  master_user_secret_kms_key_id = aws_kms_key.rds.arn

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = true

  parameter_group_name = aws_db_parameter_group.postgres.name

  backup_retention_period   = 30
  backup_window             = "02:00-03:00"
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project}-${var.environment}-pg-final"
  copy_tags_to_snapshot     = true

  maintenance_window         = "Sun:05:00-Sun:06:00"
  auto_minor_version_upgrade = true

  monitoring_interval          = 60
  monitoring_role_arn          = aws_iam_role.rds_enhanced_monitoring.arn
  performance_insights_enabled = true
  performance_insights_retention_period = 7
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]

  deletion_protection = true
  iam_database_authentication_enabled = true  # IAM auth for passwordless connections

  tags = {
    Name        = "${var.project}-${var.environment}-postgres"
    Environment = var.environment
  }
}
```

---

## Terraform: Subnet Group and Security Group

```hcl
resource "aws_db_subnet_group" "main" {
  name       = "${var.project}-${var.environment}-rds"
  subnet_ids = var.private_subnet_ids  # Private subnets across at least 2 AZs

  tags = {
    Name = "${var.project}-${var.environment}-rds-subnet-group"
  }
}

resource "aws_security_group" "rds" {
  name        = "${var.project}-${var.environment}-rds"
  description = "RDS security group — allow MySQL/Postgres from app tier only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "MySQL from application tier"
    from_port       = 3306
    to_port         = 3306
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  ingress {
    description     = "PostgreSQL from application tier"
    from_port       = 5432
    to_port         = 5432
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

## Terraform: Parameter Groups

```hcl
# MySQL 8.0 parameter group
resource "aws_db_parameter_group" "mysql" {
  name   = "${var.project}-mysql80"
  family = "mysql8.0"

  parameter {
    name  = "slow_query_log"
    value = "1"
  }
  parameter {
    name  = "long_query_time"
    value = "1"  # Log queries taking > 1 second
  }
  parameter {
    name  = "general_log"
    value = "0"  # Enable only for debugging (high volume)
  }
  parameter {
    name  = "max_connections"
    value = "500"
  }
  parameter {
    name  = "innodb_buffer_pool_size"
    value = "{DBInstanceClassMemory*3/4}"  # 75% of instance memory
  }
  parameter {
    name         = "binlog_format"
    value        = "ROW"
    apply_method = "pending-reboot"
  }
}

# PostgreSQL 16 parameter group
resource "aws_db_parameter_group" "postgres" {
  name   = "${var.project}-postgres16"
  family = "postgres16"

  parameter {
    name  = "log_min_duration_statement"
    value = "1000"  # Log queries > 1000ms
  }
  parameter {
    name  = "log_connections"
    value = "1"
  }
  parameter {
    name  = "log_disconnections"
    value = "1"
  }
  parameter {
    name  = "log_lock_waits"
    value = "1"
  }
  parameter {
    name  = "shared_preload_libraries"
    value = "pg_stat_statements"
    apply_method = "pending-reboot"
  }
  parameter {
    name  = "pg_stat_statements.track"
    value = "ALL"
  }
}
```

---

## Read Replica Setup

```hcl
resource "aws_db_instance" "read_replica" {
  identifier             = "${var.project}-${var.environment}-replica"
  replicate_source_db    = aws_db_instance.main.identifier
  instance_class         = var.replica_instance_class
  publicly_accessible    = false
  vpc_security_group_ids = [aws_security_group.rds.id]
  storage_encrypted      = true

  monitoring_interval          = 60
  monitoring_role_arn          = aws_iam_role.rds_enhanced_monitoring.arn
  performance_insights_enabled = true

  # Replicas inherit backups from primary — can override
  backup_retention_period = 0  # No backups on replica

  auto_minor_version_upgrade = true

  tags = {
    Name = "${var.project}-${var.environment}-read-replica"
    Role = "read-replica"
  }
}
```

---

## CloudWatch Alarms

```hcl
locals {
  rds_alarms = {
    high_cpu = {
      metric    = "CPUUtilization"
      threshold = 80
      desc      = "RDS CPU > 80%"
    }
    low_storage = {
      metric    = "FreeStorageSpace"
      threshold = 10737418240  # 10 GB in bytes
      desc      = "RDS free storage < 10 GB"
      comparison = "LessThanThreshold"
    }
    high_connections = {
      metric    = "DatabaseConnections"
      threshold = 400
      desc      = "RDS connections > 400"
    }
    failover = {
      metric    = "FailedSQLServerAgentJobsCount"
      threshold = 1
      desc      = "RDS failover detected"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "rds" {
  for_each = local.rds_alarms

  alarm_name          = "${var.project}-rds-${each.key}"
  comparison_operator = lookup(each.value, "comparison", "GreaterThanOrEqualToThreshold")
  evaluation_periods  = 2
  metric_name         = each.value.metric
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = each.value.threshold
  alarm_description   = each.value.desc
  alarm_actions       = [var.alarm_sns_arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }
}
```

---

## Cost Implications

| Instance Class | vCPU | RAM | Monthly Cost (us-east-1) |
|----------------|------|-----|--------------------------|
| db.t3.micro | 2 | 1 GB | ~$12 (single AZ) |
| db.t3.medium | 2 | 4 GB | ~$51 (single AZ) |
| db.r6g.large | 2 | 16 GB | ~$175 (single AZ) |
| db.r6g.xlarge | 4 | 32 GB | ~$350 (single AZ) |
| db.r6g.2xlarge | 8 | 64 GB | ~$700 (single AZ) |

- Multi-AZ doubles the instance cost
- Storage: gp3 = $0.115/GB/month + IOPS above 3000
- Performance Insights: 7 days free; 731 days = $0.02/vCPU/hour
- Backups: first 100% of provisioned storage free per month

**Optimization:** Reserved Instances for 1-3 year term save 30-60%.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| `publicly_accessible = true` | Always false — access via app servers in VPC |
| Default parameter group | Create custom parameter group — default is immutable |
| No Multi-AZ in production | Always enable; 60-120 second failover vs hours manual recovery |
| `skip_final_snapshot = true` | Set to false; add final_snapshot_identifier |
| No `deletion_protection` | Enable deletion_protection = true |
| Low backup_retention_period | Minimum 30 days for production; consider cross-region replication |
| No storage autoscaling | Set max_allocated_storage to prevent "out of storage" incidents |
| Not enabling Performance Insights | Free for 7 days — no reason to skip it |

---

## Verification Commands

```bash
# Check RDS instance status
aws rds describe-db-instances \
  --db-instance-identifier prod-mysql \
  --query 'DBInstances[0].{Status:DBInstanceStatus,MultiAZ:MultiAZ,StorageEncrypted:StorageEncrypted,BackupRetention:BackupRetentionPeriod}'

# Test connectivity from EC2/ECS
mysql -h <rds-endpoint> -u <user> -p <database> -e "SELECT VERSION();"

# Check recent events (failovers, backups, etc.)
aws rds describe-events \
  --source-identifier prod-mysql \
  --source-type db-instance \
  --duration 1440  # Last 24 hours

# List available snapshots
aws rds describe-db-snapshots \
  --db-instance-identifier prod-mysql \
  --query 'DBSnapshots[*].{Snapshot:DBSnapshotIdentifier,Status:Status,Created:SnapshotCreateTime}'

# Check slow query log
aws rds download-db-log-file-portion \
  --db-instance-identifier prod-mysql \
  --log-file-name slowquery/mysql-slowquery.log \
  --output text
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
