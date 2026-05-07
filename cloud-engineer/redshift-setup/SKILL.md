# Redshift Setup - Complete Skill Documentation

**name:** Redshift Setup

**description:** Deploy Amazon Redshift data warehouse clusters with workload management (WLM) queues, Redshift Spectrum for S3 data lake queries, AWS Glue ETL integration, column-level security, automatic table optimization, and performance monitoring for enterprise analytics workloads.

---

## Your Expertise

Senior Data Warehouse and Analytics Engineer with 12+ years building Redshift-based analytics platforms. AWS Database Specialty and Data Analytics Specialty certified. Designed Redshift architectures powering petabyte-scale data warehouses for retail, fintech, and media companies — sub-second dashboards, near-real-time data pipelines, and cost-optimized storage strategies.

**Expert in:**
- Cluster sizing — node types (RA3, DC2), slices, storage separation with RA3
- Distribution styles — EVEN, KEY, ALL — choosing for join performance
- Sort keys — compound vs interleaved, choosing for filter performance
- WLM — automatic WLM vs manual queues, concurrency scaling, query priorities
- Redshift Spectrum — query S3 directly from Redshift, external tables, partition pruning
- Glue ETL — crawler-based catalog, Glue jobs for transformation, Redshift connections
- Security — VPC, column-level security, row-level security, data masking
- AQUA — Advanced Query Accelerator for hardware-accelerated queries on RA3

Redshift bridges the gap between raw S3 data lake and business intelligence — fast enough for interactive queries, scalable enough for petabyte datasets.

---

## Common Rules

**MANDATORY RULES FOR EVERY REDSHIFT TASK:**

1. **RA3 NODES FOR NEW CLUSTERS** — DC2 nodes couple compute and storage; you pay for both regardless of use. RA3 separates managed storage (S3-backed) from compute — scale each independently. Always use RA3 for new deployments.

2. **DISTRIBUTION KEY DRIVES JOIN PERFORMANCE** — Tables joined on a common column should use that column as DISTKEY. Co-located data eliminates network shuffling. Wrong distribution = every join causes full data redistribution across all nodes.

3. **SORT KEY DRIVES FILTER PERFORMANCE** — The sort key is how Redshift skips blocks (zone maps). If you always filter by `order_date`, sort by `order_date`. Compound sort keys work for left-prefix queries; interleaved for multi-column equal weight filters.

4. **NEVER USE SUPERUSER FOR APPLICATION QUERIES** — Create dedicated database users with only SELECT on needed schemas. The `awsuser` superuser is for admin only. Application users must use fine-grained permissions.

5. **VACUUM AND ANALYZE REGULARLY** — Redshift marks deleted rows as soft-deletes (they still occupy space). `VACUUM` reclaims space and re-sorts blocks. `ANALYZE` updates statistics. Schedule both weekly minimum; auto vacuum handles most cases in recent versions.

6. **NO AI TOOL REFERENCES** — No mentions in cluster configs, WLM policies, or ETL job scripts. Output reads as data warehouse engineer work.

---

## Node Type Selection

| Node Type | Use Case | Storage | Max Cluster |
|-----------|----------|---------|-------------|
| RA3.xlplus | Dev/small prod | Managed S3 | 32 nodes |
| RA3.4xlarge | Medium analytics | Managed S3 | 32 nodes |
| RA3.16xlarge | Large enterprise | Managed S3 | 128 nodes |
| DC2.large | Small, compute-heavy | 160 GB SSD | 32 nodes |
| DC2.8xlarge | High-perf compute | 2.56 TB SSD | 128 nodes |

**Always choose RA3** for new deployments unless you need DC2's SSD performance for hot data.

---

## Terraform: Redshift Cluster

```hcl
resource "aws_redshift_cluster" "main" {
  cluster_identifier = "${var.project}-${var.environment}"
  database_name      = var.database_name
  master_username    = var.master_username
  master_password    = var.master_password  # Store in Secrets Manager

  node_type       = "ra3.4xlarge"
  cluster_type    = "multi-node"
  number_of_nodes = 4  # Minimum 2 for multi-node

  cluster_subnet_group_name  = aws_redshift_subnet_group.main.name
  vpc_security_group_ids     = [aws_security_group.redshift.id]
  publicly_accessible        = false

  encrypted  = true
  kms_key_id = aws_kms_key.redshift.arn

  cluster_parameter_group_name = aws_redshift_parameter_group.main.name

  # Snapshots
  automated_snapshot_retention_period = 30
  snapshot_identifier                 = null  # For restore from snapshot
  final_snapshot_identifier           = "${var.project}-${var.environment}-final"
  skip_final_snapshot                 = false

  # Maintenance
  preferred_maintenance_window   = "Mon:04:00-Mon:05:00"
  apply_immediately              = false
  allow_version_upgrade          = true
  automated_snapshot_copy {
    destination_region = var.dr_region
    retention_period   = 7
  }

  # Enhanced VPC routing — forces all COPY/UNLOAD to go through VPC (no internet)
  enhanced_vpc_routing = true

  # Logging to S3
  logging {
    enable        = true
    bucket_name   = aws_s3_bucket.redshift_logs.id
    s3_key_prefix = "redshift-logs/"
  }

  # Aqua acceleration (RA3 only)
  aqua_configuration_status = "auto"

  iam_roles = [aws_iam_role.redshift.arn]

  tags = {
    Name        = "${var.project}-redshift-${var.environment}"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## Terraform: Subnet Group and Security Group

```hcl
resource "aws_redshift_subnet_group" "main" {
  name       = "${var.project}-redshift-subnet-group"
  subnet_ids = var.private_subnet_ids

  tags = { Name = "${var.project}-redshift-subnet-group" }
}

resource "aws_security_group" "redshift" {
  name        = "${var.project}-${var.environment}-redshift"
  description = "Redshift — allow Redshift port from BI tools and ETL only"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redshift from BI tools"
    from_port       = 5439
    to_port         = 5439
    protocol        = "tcp"
    security_groups = [aws_security_group.bi_tools.id]
  }

  ingress {
    description = "Redshift from Glue"
    from_port   = 5439
    to_port     = 5439
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]  # Glue uses managed IPs; restrict further with Glue VPC connection
  }
}
```

---

## Terraform: Parameter Group (WLM)

```hcl
resource "aws_redshift_parameter_group" "main" {
  name   = "${var.project}-redshift-params"
  family = "redshift-1.0"

  parameter {
    name  = "enable_user_activity_logging"
    value = "true"
  }

  parameter {
    name  = "require_ssl"
    value = "true"
  }

  parameter {
    name  = "auto_analyze"
    value = "true"
  }

  parameter {
    name  = "auto_mv"
    value = "true"  # Automatic materialized views
  }

  # WLM configuration — automatic mode (recommended)
  parameter {
    name = "wlm_json_configuration"
    value = jsonencode([
      {
        auto_wlm = true
        # Automatic WLM manages concurrency scaling automatically
      }
    ])
  }
}
```

---

## Manual WLM with Queues

```json
[
  {
    "name": "ETL Queue",
    "query_group": ["etl_load"],
    "user_group": ["etl_user"],
    "query_concurrency": 5,
    "memory_percent_to_use": 30,
    "priority": "low",
    "query_execution_time": 3600
  },
  {
    "name": "Dashboard Queue",
    "query_group": ["dashboard"],
    "user_group": ["bi_users"],
    "query_concurrency": 15,
    "memory_percent_to_use": 40,
    "priority": "highest",
    "concurrency_scaling": "auto",
    "query_execution_time": 30
  },
  {
    "name": "Default Queue",
    "query_concurrency": 10,
    "memory_percent_to_use": 30,
    "priority": "normal"
  }
]
```

---

## Redshift Spectrum Setup

```sql
-- Create external schema pointing to Glue catalog
CREATE EXTERNAL SCHEMA spectrum_data
FROM DATA CATALOG
DATABASE 'analytics_db'
IAM_ROLE 'arn:aws:iam::123456789012:role/RedshiftSpectrumRole'
CREATE EXTERNAL DATABASE IF NOT EXISTS;

-- Create external table for S3 data
CREATE EXTERNAL TABLE spectrum_data.events (
    event_id    VARCHAR(36),
    user_id     BIGINT,
    event_type  VARCHAR(50),
    created_at  TIMESTAMP,
    properties  SUPER  -- Semi-structured JSON
)
PARTITIONED BY (year INT, month INT, day INT)
STORED AS PARQUET
LOCATION 's3://my-data-lake/events/';

-- Add partitions
ALTER TABLE spectrum_data.events ADD PARTITION (year=2026, month=5, day=8)
LOCATION 's3://my-data-lake/events/year=2026/month=05/day=08/';

-- Query joining Redshift table with S3 data
SELECT u.name, COUNT(e.event_id) as event_count
FROM users u
JOIN spectrum_data.events e ON u.id = e.user_id
WHERE e.year = 2026 AND e.month = 5
GROUP BY u.name
ORDER BY event_count DESC;
```

---

## Glue ETL Integration

```hcl
resource "aws_glue_job" "etl_load" {
  name     = "${var.project}-etl-s3-to-redshift"
  role_arn = aws_iam_role.glue.arn

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_bucket.glue_scripts.id}/scripts/etl_load.py"
    python_version  = "3"
  }

  glue_version      = "4.0"
  worker_type       = "G.1X"
  number_of_workers = 10

  connections = [aws_glue_connection.redshift.name]

  default_arguments = {
    "--job-language"            = "python"
    "--enable-metrics"          = ""
    "--enable-spark-ui"         = "true"
    "--enable-job-bookmarks"    = "enable"
    "--TempDir"                 = "s3://${aws_s3_bucket.glue_temp.id}/temp/"
    "--redshift_connection"     = aws_glue_connection.redshift.name
    "--target_table"            = "analytics.orders"
  }
}

resource "aws_glue_connection" "redshift" {
  name = "${var.project}-redshift-connection"

  connection_properties = {
    JDBC_CONNECTION_URL = "jdbc:redshift://${aws_redshift_cluster.main.endpoint}/analytics"
    USERNAME            = var.master_username
    PASSWORD            = var.master_password
  }

  physical_connection_requirements {
    availability_zone      = var.availability_zones[0]
    security_group_id_list = [aws_security_group.glue.id]
    subnet_id              = var.private_subnet_ids[0]
  }
}
```

---

## Table Design Best Practices

```sql
-- Fact table: large, queried with date filter, joined to dimensions on order_id
CREATE TABLE fact_orders (
    order_id    BIGINT NOT NULL,
    customer_id BIGINT NOT NULL,
    product_id  BIGINT NOT NULL,
    order_date  DATE NOT NULL,
    revenue     DECIMAL(10,2),
    quantity    INT
)
DISTKEY(customer_id)           -- Distributes data for customer join co-location
SORTKEY(order_date)            -- Zone map skips blocks outside date range
ENCODE AUTO;                   -- Automatic columnar compression

-- Dimension table: small, joined to fact
CREATE TABLE dim_customers (
    customer_id BIGINT NOT NULL,
    name        VARCHAR(200),
    country     VARCHAR(100)
)
DISTSTYLE ALL                  -- Replicate to all nodes (small table = cheap)
SORTKEY(customer_id)
ENCODE AUTO;
```

---

## Cost Implications

| Node Type | Monthly Cost Per Node |
|-----------|----------------------|
| RA3.xlplus | ~$330 |
| RA3.4xlarge | ~$990 |
| RA3.16xlarge | ~$3,260 |
| Managed storage (RA3) | $0.024/GB-month |
| Spectrum queries | $5.00/TB scanned |
| Concurrency scaling | $6.00/RPU-hour |

**Reserved nodes (3-year):** Up to 75% discount.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| DISTSTYLE EVEN on frequently joined tables | Use DISTKEY on join column for co-location |
| No SORTKEY on filter columns | Add sort key matching your most common WHERE clause |
| Not running VACUUM after bulk loads | Schedule VACUUM weekly minimum |
| Superuser for BI tools | Create read-only users with schema-level SELECT grants |
| Not using enhanced VPC routing | Enable enhanced_vpc_routing = true to prevent internet traffic |
| DC2 nodes for new clusters | Use RA3 for managed storage separation |
| Single-node for production | Minimum 2 nodes for Multi-AZ and performance |

---

## Verification Commands

```bash
# Cluster status
aws redshift describe-clusters \
  --cluster-identifier prod-analytics \
  --query 'Clusters[0].{Status:ClusterStatus,Encrypted:Encrypted,Nodes:NumberOfNodes,NodeType:NodeType}'

# Query performance (from SQL client)
SELECT query, datediff(seconds, starttime, endtime) as elapsed_seconds,
       aborted, label
FROM stl_query
WHERE userid > 1
ORDER BY starttime DESC LIMIT 20;

# Check WLM queue waits
SELECT w.service_class, COUNT(w.query) as waiting, AVG(w.queue_time) as avg_wait_ms
FROM stv_wlm_query_state w
WHERE w.state = 'QueuedWaiting'
GROUP BY w.service_class;

# Table scan performance
SELECT schemaname, tablename, scanned_blocks, processed_blocks,
       ROUND(100.0*scanned_blocks/NULLIF(processed_blocks,0),2) as pct_scanned
FROM svv_table_info
ORDER BY scanned_blocks DESC LIMIT 20;
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
