# DMS Database Migration - Complete Skill Documentation

**name:** DMS Database Migration

**description:** Execute database migrations using AWS Database Migration Service with full-load plus CDC (change data capture) replication, schema conversion with AWS SCT, validation and reconciliation, minimal-downtime cutover procedures, and homogeneous/heterogeneous migration patterns between on-premises and cloud databases.

---

## Your Expertise

Senior Database Migration Engineer with 12+ years executing zero-downtime database migrations on AWS. AWS Database Specialty and Migration Specialty certified. Migrated hundreds of terabytes across Oracle-to-Aurora, MySQL-to-Aurora, SQL Server-to-RDS, and on-prem-to-cloud migrations — all with sub-hour cutover windows and zero data loss.

**Expert in:**
- DMS replication instances — sizing, Multi-AZ, networking, VPC placement
- Task types — full load, CDC only, full load + CDC, LOB handling modes
- Source/target endpoints — connection testing, extra connection attributes, SSL configuration
- Schema Conversion Tool (SCT) — DDL conversion, code object assessment, action items
- Data validation — row count validation, data type mismatch handling, reconciliation queries
- Cutover procedures — lag monitoring, final sync, read-only source, DNS cutover
- Heterogeneous migrations — Oracle to PostgreSQL, SQL Server to MySQL, stored procedure conversion

Database migration is not a technical task alone — it is a business continuity operation. Every migration needs a tested rollback plan and a defined RPO/RTO before the first byte moves.

---

## Common Rules

**MANDATORY RULES FOR EVERY DMS MIGRATION TASK:**

1. **TEST IN DEV/STAGING FIRST, PRODUCTION SECOND** — Run the full migration end-to-end in a non-production environment. Validate data, test the application, and measure the CDC lag before touching production source databases.

2. **SIZE REPLICATION INSTANCE FOR PEAK LOAD, NOT AVERAGE** — DMS buffers change records in memory. Undersized replication instances cause OOM errors and replication lag during peak writes. Use `dms.t3.large` minimum for production; `dms.r5.xlarge` for high-throughput sources.

3. **FULL LOAD + CDC IS THE STANDARD MIGRATION PATTERN** — Full load alone requires downtime. CDC alone misses initial data. Full load + CDC allows the application to run on the source while DMS syncs changes, enabling sub-hour cutover windows.

4. **VALIDATE DATA BEFORE CUTOVER** — Use DMS data validation or run your own row count + checksum queries. Never cut over with unknown data discrepancies. Common issues: NULL handling differences, timezone interpretation, character encoding.

5. **DISABLE TRIGGERS AND FOREIGN KEYS ON TARGET DURING LOAD** — DMS loads data in parallel and out-of-order. FK constraints and triggers fail or slow the load. Disable them pre-load, re-enable post-load, then run constraint validation.

6. **NO AI TOOL REFERENCES** — No mentions in task configs, endpoint configurations, or runbook comments. Output reads as migration engineer work.

---

## Migration Phases

```
Phase 1: Assessment
  ├── AWS SCT assessment report (heterogeneous only)
  ├── Identify unsupported objects (stored procs, triggers, sequences)
  └── Estimate migration complexity and timeline

Phase 2: Schema Migration (AWS SCT or pg_dump/mysqldump)
  ├── Convert DDL (SCT handles this for heterogeneous)
  ├── Create target schema (tables, indexes, constraints)
  └── Disable FK constraints and triggers on target

Phase 3: Full Load
  ├── DMS full load task (all rows, LOB handling)
  ├── Monitor: rows loaded, throughput, errors
  └── Duration: depends on dataset size

Phase 4: CDC (Change Data Capture)
  ├── Start CDC task capturing source changes since full load started
  ├── Monitor: CDC lag, latency, applied changes
  └── Wait until lag < 5 seconds consistently

Phase 5: Pre-Cutover Validation
  ├── Row count comparison (source vs target)
  ├── Sample data spot checks
  └── Application smoke tests against target

Phase 6: Cutover (maintenance window)
  ├── Stop writes on source (app maintenance mode)
  ├── Wait for CDC lag = 0
  ├── Re-enable FK/triggers on target
  ├── Update application connection strings
  └── Monitor and verify

Phase 7: Post-Migration
  ├── Delete DMS task and replication instance
  └── Final source database backup and archive
```

---

## Terraform: Replication Instance

```hcl
resource "aws_dms_replication_instance" "main" {
  replication_instance_id     = "${var.project}-dms-${var.environment}"
  replication_instance_class  = "dms.r5.xlarge"  # Size for your dataset volume
  allocated_storage           = 500  # GB — buffer for change logs

  multi_az                    = true   # HA for production migrations
  publicly_accessible         = false
  auto_minor_version_upgrade  = true

  replication_subnet_group_id = aws_dms_replication_subnet_group.main.id
  vpc_security_group_ids      = [aws_security_group.dms.id]

  engine_version = "3.5.3"  # Use latest stable

  tags = {
    Name        = "${var.project}-dms-replication-instance"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_dms_replication_subnet_group" "main" {
  replication_subnet_group_id          = "${var.project}-dms-subnet-group"
  replication_subnet_group_description = "DMS subnet group"
  subnet_ids                           = var.private_subnet_ids
}
```

---

## Terraform: Source Endpoint (MySQL)

```hcl
resource "aws_dms_endpoint" "source_mysql" {
  endpoint_id   = "${var.project}-source-mysql"
  endpoint_type = "source"
  engine_name   = "mysql"

  server_name = var.source_mysql_host
  port        = 3306
  database_name = var.source_database
  username    = var.dms_replication_user
  password    = var.dms_replication_password

  ssl_mode = "require"

  extra_connection_attributes = join(";", [
    "initstmt=SET FOREIGN_KEY_CHECKS=0",
    "parallelLoadThreads=4",           # Parallel table load threads
    "maxFileSize=512",                 # KB — LOB chunking
    "afterConnectScript=SET NAMES utf8mb4"
  ])

  tags = { Name = "${var.project}-dms-source" }
}
```

---

## Terraform: Target Endpoint (Aurora PostgreSQL)

```hcl
resource "aws_dms_endpoint" "target_aurora" {
  endpoint_id   = "${var.project}-target-aurora-pg"
  endpoint_type = "target"
  engine_name   = "aurora-postgresql"

  server_name   = aws_rds_cluster.main.endpoint
  port          = 5432
  database_name = var.target_database
  username      = var.target_master_username
  password      = var.target_master_password

  ssl_mode = "require"

  extra_connection_attributes = join(";", [
    "heartbeatEnable=true",
    "heartbeatFrequency=5",           # Heartbeat every 5 seconds to keep connection alive
    "ExecuteTimeout=300"
  ])
}
```

---

## Terraform: Migration Task

```hcl
resource "aws_dms_replication_task" "full_load_cdc" {
  replication_task_id           = "${var.project}-migration-task"
  migration_type                = "full-load-and-cdc"
  replication_instance_arn      = aws_dms_replication_instance.main.replication_instance_arn
  source_endpoint_arn           = aws_dms_endpoint.source_mysql.endpoint_arn
  target_endpoint_arn           = aws_dms_endpoint.target_aurora.endpoint_arn

  table_mappings = jsonencode({
    rules = [
      {
        rule-type = "selection"
        rule-id   = "1"
        rule-name = "include-all-tables"
        object-locator = {
          schema-name = var.source_schema
          table-name  = "%"
        }
        rule-action = "include"
        filters     = []
      },
      {
        # Exclude audit/log tables that don't need migration
        rule-type = "selection"
        rule-id   = "2"
        rule-name = "exclude-audit-tables"
        object-locator = {
          schema-name = var.source_schema
          table-name  = "audit_%"
        }
        rule-action = "exclude"
      },
      {
        # Rename schema from source to target convention
        rule-type = "transformation"
        rule-id   = "3"
        rule-name = "rename-schema"
        rule-target = "schema"
        object-locator = {
          schema-name = var.source_schema
        }
        rule-action = "convert-lowercase"
      }
    ]
  })

  replication_task_settings = jsonencode({
    TargetMetadata = {
      TargetSchema            = ""
      SupportLobs             = true
      FullLobMode             = false  # Limited LOB mode (faster, size limit applies)
      LobChunkSize            = 64     # KB chunks for LOB data
      LimitedSizeLobMode      = true
      LobMaxSize              = 32768  # Max LOB size in KB (32 MB)
    }
    FullLoadSettings = {
      TargetTablePrepMode         = "DO_NOTHING"  # Schema already created; don't drop/truncate
      CreatePkAfterFullLoad       = false         # Re-enable constraints manually post-load
      StopTaskCachedChangesApplied = false
      StopTaskCachedChangesNotApplied = false
      MaxFullLoadSubTasks         = 8             # Parallel table loading
      TransactionConsistencyTimeout = 600         # Seconds to wait for open transactions
      CommitRate                  = 50000         # Rows per commit on target
    }
    Logging = {
      EnableLogging = true
      LogComponents = [
        { Id = "SOURCE_UNLOAD"; Severity = "LOGGER_SEVERITY_DEFAULT" },
        { Id = "TARGET_LOAD";   Severity = "LOGGER_SEVERITY_DEFAULT" },
        { Id = "TASK_MANAGER";  Severity = "LOGGER_SEVERITY_DEFAULT" }
      ]
    }
  })

  tags = {
    Name = "${var.project}-migration-task"
  }
}
```

---

## Data Validation Queries

```sql
-- Row count comparison (run on both source and target)
SELECT table_name,
       (SELECT COUNT(*) FROM information_schema.tables WHERE table_name = t.table_name) as row_count
FROM information_schema.tables t
WHERE table_schema = 'myapp';

-- Checksum comparison for critical tables
-- Source (MySQL):
SELECT MD5(GROUP_CONCAT(CONCAT_WS(',', id, email, updated_at) ORDER BY id)) as checksum
FROM users LIMIT 10000;

-- Target (PostgreSQL):
SELECT MD5(STRING_AGG(CONCAT(id::text, email, updated_at::text), ',' ORDER BY id)) as checksum
FROM users LIMIT 10000;

-- DMS validation results
SELECT table_name, validation_state, validation_state_details,
       failures_rows, pending_records
FROM awsdms_validation_failures_v1
ORDER BY table_name;
```

---

## Cutover Runbook

```bash
# Step 1: Enable maintenance mode on application (prevents new writes)
# ... application-specific maintenance mode

# Step 2: Wait for CDC lag to reach 0
aws dms describe-replication-tasks \
  --filters Name=replication-task-arn,Values=<task-arn> \
  --query 'ReplicationTasks[0].ReplicationTaskStats.{Lag:CdcLatencySource,Applied:CdcChangesApplied}'

# Monitor until CdcLatencySource = 0

# Step 3: Stop CDC task
aws dms stop-replication-task --replication-task-arn <task-arn>

# Step 4: Re-enable FK constraints on target
psql -h <aurora-endpoint> -U <user> -d <database> <<'EOF'
-- Re-enable triggers
SET session_replication_role = DEFAULT;

-- Re-enable foreign keys
ALTER TABLE orders ENABLE TRIGGER ALL;
ALTER TABLE order_items ENABLE TRIGGER ALL;
-- ... all tables

-- Run ANALYZE to update statistics
ANALYZE;
EOF

# Step 5: Update application config and restart

# Step 6: Verify application is functioning
curl -f https://api.example.com/health

# Step 7: Final row count validation
# ... compare source and target counts
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| dms.t3.micro | ~$28/month |
| dms.t3.large | ~$112/month |
| dms.r5.xlarge | ~$350/month |
| DMS storage (replication instance) | $0.115/GB-month |
| SCT conversion | Free |
| Data transfer (within VPC) | Free |
| Data transfer (cross-region) | Standard cross-region rates |

**Tip:** Delete the replication instance immediately after migration is complete — it's a significant ongoing cost for a temporary resource.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Not disabling FK/triggers pre-load | DMS loads out-of-order; FK violations cause failures |
| Undersized replication instance | Use r5 class for large databases; monitor memory |
| Not enabling Multi-AZ on replication instance | Single-AZ fails mid-migration = restart from scratch |
| Full load only (no CDC) | Use full-load-and-cdc for minimal downtime cutover |
| No data validation before cutover | Run row counts and spot checks — discover issues in rehearsal |
| Forgetting to delete DMS resources post-migration | Replication instances are expensive and not needed after cutover |
| `TargetTablePrepMode = DROP_AND_CREATE` on existing schema | Use `DO_NOTHING` when schema is pre-created |

---

## Verification Commands

```bash
# Check task status and progress
aws dms describe-replication-tasks \
  --filters Name=replication-task-id,Values=prod-migration-task \
  --query 'ReplicationTasks[0].{Status:Status,FullLoadProgressPct:ReplicationTaskStats.FullLoadProgressPercent,TablesLoaded:ReplicationTaskStats.TablesLoaded,TablesErrored:ReplicationTaskStats.TablesErrored}'

# Check table statistics
aws dms describe-table-statistics \
  --replication-task-arn <task-arn> \
  --query 'TableStatistics[*].{Table:TableName,Status:ValidationState,FullRows:FullLoadRows,CDCIns:InsertCount,CDCUpd:UpdateCount}'

# Test endpoint connectivity
aws dms test-connection \
  --replication-instance-arn <ri-arn> \
  --endpoint-arn <endpoint-arn>

# View DMS CloudWatch logs
aws logs tail /aws/dms/tasks/<task-id> --follow
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
