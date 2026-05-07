# RDS Proxy Setup - Complete Skill Documentation

**name:** RDS Proxy Setup

**description:** Configure Amazon RDS Proxy for connection pooling to handle Lambda and serverless workload connection spikes, reduce database connection overhead, enable IAM database authentication, and provide automatic failover for RDS and Aurora clusters with zero application code changes.

---

## Your Expertise

Senior Cloud Database and Serverless Engineer with 12+ years designing data access layers for serverless and containerized workloads on AWS. AWS Database Specialty and Solutions Architect Professional certified. Solved "too many connections" database failures for Lambda-heavy platforms by deploying RDS Proxy — reducing connection counts by 99% while improving application throughput.

**Expert in:**
- RDS Proxy architecture — proxy endpoint, connection pooling, pinning avoidance
- IAM authentication through proxy — removing hardcoded DB passwords from Lambda
- Lambda to RDS Proxy patterns — connection reuse in Lambda execution environment
- Target groups — RDS instance and Aurora cluster targets, failover routing
- Proxy pinning — what causes it, how to avoid it, monitoring pin rate
- Secrets Manager integration — proxy fetches credentials from Secrets Manager automatically
- Connection limits — calculating MaxConnectionsPercent, MaxIdleConnectionsPercent

A Lambda function that opens a new database connection on every invocation kills the database at scale. RDS Proxy is the only correct solution for serverless database access patterns.

---

## Common Rules

**MANDATORY RULES FOR EVERY RDS PROXY TASK:**

1. **PROXY IS MANDATORY FOR LAMBDA → RDS** — Lambda scales to thousands of concurrent executions. Each execution without proxy = one database connection. At 1,000 concurrent Lambdas, that's 1,000 DB connections simultaneously. RDS Proxy pools these behind a much smaller set of backend connections.

2. **USE IAM AUTH — NO HARDCODED PASSWORDS** — RDS Proxy supports IAM authentication, which means Lambda functions generate temporary credentials using `rds:connect` IAM permission. No database passwords in environment variables, no rotation required. Always configure `iam_auth = "REQUIRED"`.

3. **AVOID PINNING** — Proxy pinning breaks connection multiplexing (one backend connection serves only one client). Pinning is triggered by: SET statements, multi-statement transactions, prepared statements without deallocating. Design queries to avoid these patterns.

4. **PROXY IN SAME VPC AS DATABASE** — RDS Proxy must be in the same VPC as the target RDS instance or Aurora cluster. Lambda functions accessing the proxy must also be VPC-enabled with the correct security groups.

5. **PROXY ENDPOINTS FOR READ/WRITE SPLIT** — Create a reader proxy endpoint for read-only Lambda functions. Reader endpoint routes to Aurora read replicas, reducing load on the writer. Writer endpoint for mutations.

6. **NO AI TOOL REFERENCES** — No mentions in proxy configurations, Lambda handlers, or Secrets Manager references. Output reads as infrastructure engineer work.

---

## Architecture

```
Lambda Functions (1000 concurrent)
    │
    └── RDS Proxy (pools 1000 → 50 connections)
          │
          ├── Writer Endpoint → Aurora Writer / RDS Primary
          └── Reader Endpoint → Aurora Readers (optional)

Connection Pool:
  MaxConnectionsPercent = 70%    → 70% of DB max_connections reserved for proxy
  MaxIdleConnectionsPercent = 50% → 50% of reserved kept open as warm pool
```

---

## Terraform: RDS Proxy for Aurora

```hcl
resource "aws_db_proxy" "main" {
  name                   = "${var.project}-proxy-${var.environment}"
  debug_logging          = false
  engine_family          = "POSTGRESQL"  # or "MYSQL"
  idle_client_timeout    = 1800          # 30 minutes — close idle client connections
  require_tls            = true
  role_arn               = aws_iam_role.rds_proxy.arn
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
  vpc_subnet_ids         = var.private_subnet_ids

  auth {
    auth_scheme               = "SECRETS"
    iam_auth                  = "REQUIRED"
    secret_arn                = aws_secretsmanager_secret.db_credentials.arn
    client_password_auth_type = "POSTGRES_SCRAM_SHA_256"  # POSTGRES_MD5 for older PG
  }

  tags = {
    Name        = "${var.project}-rds-proxy-${var.environment}"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name

  connection_pool_config {
    connection_borrow_timeout    = 120   # Seconds to wait for available connection
    init_query                   = "SET application_name = 'lambda-proxy'"
    max_connections_percent      = 70    # 70% of DB max_connections
    max_idle_connections_percent = 50    # Keep 50% warm
    session_pinning_filters      = ["EXCLUDE_VARIABLE_SETS"]  # Reduces pinning from SET commands
  }
}

resource "aws_db_proxy_target" "main" {
  db_proxy_name          = aws_db_proxy.main.name
  target_group_name      = aws_db_proxy_default_target_group.main.name
  db_cluster_identifier  = aws_rds_cluster.main.cluster_identifier  # Use db_instance_identifier for RDS
}

# Reader endpoint for read-only Lambda functions
resource "aws_db_proxy_endpoint" "reader" {
  db_proxy_name          = aws_db_proxy.main.name
  db_proxy_endpoint_name = "${var.project}-proxy-reader"
  vpc_subnet_ids         = var.private_subnet_ids
  vpc_security_group_ids = [aws_security_group.rds_proxy.id]
  target_role            = "READ_ONLY"
}
```

---

## IAM Role for RDS Proxy

```hcl
resource "aws_iam_role" "rds_proxy" {
  name = "${var.project}-rds-proxy-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "rds_proxy_secrets" {
  name = "${var.project}-rds-proxy-secrets"
  role = aws_iam_role.rds_proxy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = aws_secretsmanager_secret.db_credentials.arn
      },
      {
        Effect = "Allow"
        Action = ["kms:Decrypt"]
        Resource = aws_kms_key.secrets.arn
        Condition = {
          StringEquals = {
            "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}
```

---

## Lambda IAM Permission for IAM Auth

```hcl
resource "aws_iam_role_policy" "lambda_rds_connect" {
  name = "${var.project}-lambda-rds-connect"
  role = aws_iam_role.lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["rds-db:connect"]
      Resource = "arn:aws:rds-db:${var.region}:${var.account_id}:dbuser/${aws_db_proxy.main.id}/${var.db_username}"
    }]
  })
}
```

---

## Lambda Connection Pattern (Python/psycopg2)

```python
import boto3
import psycopg2
import os
import ssl

# These are set OUTSIDE the handler — reused across Lambda invocations
_connection = None

def get_db_connection():
    global _connection

    if _connection is None or _connection.closed:
        # Generate IAM auth token
        rds_client = boto3.client('rds', region_name=os.environ['AWS_REGION'])
        token = rds_client.generate_db_auth_token(
            DBHostname=os.environ['RDS_PROXY_ENDPOINT'],
            Port=5432,
            DBUsername=os.environ['DB_USERNAME'],
            Region=os.environ['AWS_REGION']
        )

        _connection = psycopg2.connect(
            host=os.environ['RDS_PROXY_ENDPOINT'],
            port=5432,
            user=os.environ['DB_USERNAME'],
            password=token,  # IAM token as password
            database=os.environ['DB_NAME'],
            sslmode='require',
            connect_timeout=5
        )
        _connection.autocommit = False

    return _connection

def handler(event, context):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM orders WHERE status = %s", ('pending',))
            count = cur.fetchone()[0]
        conn.commit()
        return {'count': count}
    except Exception as e:
        conn.rollback()
        raise
```

---

## Security Group Configuration

```hcl
resource "aws_security_group" "rds_proxy" {
  name        = "${var.project}-rds-proxy"
  description = "RDS Proxy security group"
  vpc_id      = var.vpc_id

  ingress {
    description     = "PostgreSQL from Lambda"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.lambda.id]
  }

  egress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.aurora.id]
  }
}

# Add proxy SG to Aurora's allowed ingress
resource "aws_security_group_rule" "aurora_from_proxy" {
  type                     = "ingress"
  from_port                = 5432
  to_port                  = 5432
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.rds_proxy.id
  security_group_id        = aws_security_group.aurora.id
  description              = "Allow RDS Proxy to connect to Aurora"
}
```

---

## Monitoring Pinning Rate

```hcl
resource "aws_cloudwatch_metric_alarm" "proxy_pinning" {
  alarm_name          = "${var.project}-rds-proxy-high-pinning"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "ClientConnectionsSetupFailedAuth"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_actions       = [var.alarm_sns_arn]

  dimensions = {
    ProxyName = aws_db_proxy.main.name
  }
}
```

```bash
# Monitor proxy metrics
aws cloudwatch get-metric-data \
  --metric-data-queries '[
    {"Id":"pinning","MetricStat":{"Metric":{"Namespace":"AWS/RDS","MetricName":"QueryDatabaseResults","Dimensions":[{"Name":"ProxyName","Value":"my-proxy"}]},"Period":300,"Stat":"Sum"}},
    {"Id":"connections","MetricStat":{"Metric":{"Namespace":"AWS/RDS","MetricName":"ClientConnectionsCurrent","Dimensions":[{"Name":"ProxyName","Value":"my-proxy"}]},"Period":300,"Stat":"Average"}}
  ]' \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ)
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| RDS Proxy | $0.015/vCPU-hour of target RDS/Aurora |
| db.r6g.2xlarge Aurora (8 vCPU) | $0.12/hour proxy cost |
| Example: 8 vCPU Aurora, always on | ~$87/month for proxy |

**Break-even:** If the proxy prevents a single DB crash from Lambda connection storms, it pays for itself. For Lambda workloads hitting RDS, proxy is not optional at scale.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Lambda without VPC trying to reach proxy | Lambda must be VPC-enabled with proxy's subnet/SG access |
| Hardcoded DB password in Lambda (no IAM auth) | Use iam_auth = "REQUIRED" and generate_db_auth_token |
| Connection opened outside handler (but not reused) | Initialize connection globally; reuse across invocations |
| SET commands in every query (causes pinning) | Use session_pinning_filters = ["EXCLUDE_VARIABLE_SETS"] |
| max_connections_percent = 100 | Leave headroom; set to 70-80% maximum |
| No reader endpoint for read-heavy Lambda | Add reader endpoint; route SELECT to reader target group |
| Proxy without TLS | Always require_tls = true |

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
