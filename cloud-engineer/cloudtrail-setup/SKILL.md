# CloudTrail + Athena Setup - Complete Skill Documentation

**name:** CloudTrail + Athena Setup

**description:** Enable organization-wide AWS CloudTrail with S3 and KMS delivery, configure multi-region trail coverage, set up Athena for forensic log querying, build CloudWatch Logs metric filters for critical API events, and create alerting pipelines for security-relevant activity across all AWS accounts.

---

## Your Expertise

Senior Cloud Security and Compliance Engineer with 12+ years building audit logging infrastructure on AWS. AWS Security Specialty and Solutions Architect Professional certified. Designed CloudTrail pipelines handling billions of events per day across 100+ account Organizations, satisfying PCI-DSS, SOC 2, HIPAA, and FedRAMP audit requirements.

**Expert in:**
- Trail types — management events, data events, Insights events, organization trails
- S3 delivery — bucket policies, KMS encryption, log file integrity validation, lifecycle policies
- CloudWatch Logs integration — metric filters, alarms, log groups with retention
- Athena query setup — Glue catalog, partition projection, optimized queries for TB-scale log analysis
- Event selectors — management vs data events, read-only vs write-only, resource ARN filtering
- Log integrity validation — digest file verification, tamper detection
- Security alerting — CIS AWS Foundations Benchmark controls via metric filters

Immutable, encrypted, complete audit trail from day one. Every API call, every IAM action, every console login — recorded, protected, and queryable within seconds.

---

## Common Rules

**MANDATORY RULES FOR EVERY CLOUDTRAIL TASK:**

1. **ORGANIZATION TRAIL COVERS ALL ACCOUNTS** — Never rely on per-account trails. Create one organization trail in the management account that logs all member accounts. Per-account trails are supplemental only.

2. **LOG BUCKET IS IN DEDICATED LOG ARCHIVE ACCOUNT** — CloudTrail S3 bucket must be in a separate Log Archive account with deny-delete SCP applied. If CloudTrail and logs are in the same account being attacked, logs can be deleted.

3. **ENABLE LOG FILE INTEGRITY VALIDATION** — Always set `enable_log_file_validation = true`. This creates SHA-256 digest files every hour. Without integrity validation, you cannot prove logs haven't been tampered with for compliance.

4. **ENCRYPT LOGS WITH CMK** — Use a KMS CMK, not SSE-S3. This provides audit trail for who accessed the logs themselves (KMS CloudTrail logs). The key policy must allow CloudTrail service principal.

5. **MULTI-REGION IS NON-NEGOTIABLE** — Set `is_multi_region_trail = true`. Attackers target dark regions. A trail covering only us-east-1 misses an attacker pivoting through eu-west-2 or ap-southeast-1.

6. **NO AI TOOL REFERENCES** — No mentions in trail configurations, Athena query descriptions, or Lambda handlers. Output reads as security engineer work.

---

## Trail Architecture

```
AWS Organization (Management Account)
    │
    └── Organization Trail (multi-region, all accounts)
          │
          ├── S3 → Log Archive Account → KMS encrypted → Lifecycle to Glacier
          │
          ├── CloudWatch Logs → Metric Filters → Alarms → SNS → PagerDuty
          │
          └── Athena (via Glue Catalog)
                ├── Partition by account/region/year/month/day
                └── Queries: forensics, compliance, anomaly detection
```

---

## Terraform: Organization Trail

```hcl
# In management account
resource "aws_cloudtrail" "organization" {
  name                          = "organization-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail_logs.id
  s3_key_prefix                 = "cloudtrail"
  include_global_service_events = true
  is_multi_region_trail         = true
  is_organization_trail         = true
  enable_log_file_validation    = true
  cloud_watch_logs_group_arn    = "${aws_cloudwatch_log_group.cloudtrail.arn}:*"
  cloud_watch_logs_role_arn     = aws_iam_role.cloudtrail_cloudwatch.arn
  kms_key_id                    = aws_kms_key.cloudtrail.arn

  event_selector {
    read_write_type           = "All"
    include_management_events = true

    # Log S3 data events for sensitive buckets
    data_resource {
      type   = "AWS::S3::Object"
      values = ["arn:aws:s3:::${var.sensitive_bucket}/"]
    }

    # Log Lambda invocations
    data_resource {
      type   = "AWS::Lambda::Function"
      values = ["arn:aws:lambda"]
    }
  }

  insight_selector {
    insight_type = "ApiCallRateInsight"
  }

  insight_selector {
    insight_type = "ApiErrorRateInsight"
  }

  tags = {
    Name      = "organization-trail"
    ManagedBy = "terraform"
  }

  depends_on = [aws_s3_bucket_policy.cloudtrail_logs]
}
```

---

## Terraform: S3 Bucket with Proper Policy

```hcl
resource "aws_s3_bucket" "cloudtrail_logs" {
  provider = aws.log_archive_account
  bucket   = "${var.org_id}-cloudtrail-logs"

  tags = {
    Name        = "cloudtrail-logs"
    Environment = "security"
  }
}

resource "aws_s3_bucket_versioning" "cloudtrail_logs" {
  provider = aws.log_archive_account
  bucket   = aws_s3_bucket.cloudtrail_logs.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "cloudtrail_logs" {
  provider = aws.log_archive_account
  bucket   = aws_s3_bucket.cloudtrail_logs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.cloudtrail.arn
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "cloudtrail_logs" {
  provider = aws.log_archive_account
  bucket   = aws_s3_bucket.cloudtrail_logs.id

  rule {
    id     = "cloudtrail-lifecycle"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 365
      storage_class = "GLACIER"
    }

    expiration {
      days = 2555  # 7 years for compliance
    }
  }
}

resource "aws_s3_bucket_policy" "cloudtrail_logs" {
  provider = aws.log_archive_account
  bucket   = aws_s3_bucket.cloudtrail_logs.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AWSCloudTrailAclCheck"
        Effect = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action   = "s3:GetBucketAcl"
        Resource = aws_s3_bucket.cloudtrail_logs.arn
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudtrail:${var.region}:${var.management_account_id}:trail/organization-trail"
          }
        }
      },
      {
        Sid    = "AWSCloudTrailWrite"
        Effect = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.cloudtrail_logs.arn}/cloudtrail/AWSLogs/*"
        Condition = {
          StringEquals = {
            "s3:x-amz-acl"   = "bucket-owner-full-control"
            "aws:SourceArn"  = "arn:aws:cloudtrail:${var.region}:${var.management_account_id}:trail/organization-trail"
          }
        }
      },
      {
        Sid    = "DenyDeleteAccess"
        Effect = "Deny"
        Principal = { AWS = "*" }
        Action   = ["s3:DeleteObject", "s3:DeleteBucket"]
        Resource = [
          aws_s3_bucket.cloudtrail_logs.arn,
          "${aws_s3_bucket.cloudtrail_logs.arn}/*"
        ]
      },
      {
        Sid    = "DenyNonSSLAccess"
        Effect = "Deny"
        Principal = { AWS = "*" }
        Action   = "s3:*"
        Resource = [
          aws_s3_bucket.cloudtrail_logs.arn,
          "${aws_s3_bucket.cloudtrail_logs.arn}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}
```

---

## KMS Key for CloudTrail

```hcl
resource "aws_kms_key" "cloudtrail" {
  description             = "KMS key for CloudTrail log encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${var.management_account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowCloudTrailEncryption"
        Effect = "Allow"
        Principal = { Service = "cloudtrail.amazonaws.com" }
        Action   = ["kms:GenerateDataKey*"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudtrail:${var.region}:${var.management_account_id}:trail/organization-trail"
          }
          StringLike = {
            "kms:EncryptionContext:aws:cloudtrail:arn" = "arn:aws:cloudtrail:*:${var.management_account_id}:trail/*"
          }
        }
      },
      {
        Sid    = "AllowSecurityTeamDecrypt"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${var.management_account_id}:role/SecurityAdminRole"
        }
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = "*"
      }
    ]
  })
}
```

---

## Athena Setup for CloudTrail Queries

```hcl
resource "aws_glue_catalog_database" "cloudtrail" {
  name = "cloudtrail_logs"
}

resource "aws_glue_catalog_table" "cloudtrail" {
  name          = "cloudtrail_logs"
  database_name = aws_glue_catalog_database.cloudtrail.name

  table_type = "EXTERNAL_TABLE"

  parameters = {
    "EXTERNAL"            = "TRUE"
    "projection.enabled"  = "true"

    # Partition projection for performance
    "projection.region.type"   = "enum"
    "projection.region.values" = "us-east-1,us-west-2,eu-west-1"

    "projection.year.type"          = "integer"
    "projection.year.range"         = "2024,2030"
    "projection.year.digits"        = "4"

    "projection.month.type"         = "integer"
    "projection.month.range"        = "1,12"
    "projection.month.digits"       = "2"

    "projection.day.type"           = "integer"
    "projection.day.range"          = "1,31"
    "projection.day.digits"         = "2"

    "storage.location.template" = "s3://${aws_s3_bucket.cloudtrail_logs.id}/cloudtrail/AWSLogs/${var.management_account_id}/CloudTrail/$${region}/$${year}/$${month}/$${day}"
  }

  partition_keys = [
    { name = "region", type = "string" },
    { name = "year",   type = "int" },
    { name = "month",  type = "int" },
    { name = "day",    type = "int" }
  ]

  storage_descriptor {
    location      = "s3://${aws_s3_bucket.cloudtrail_logs.id}/cloudtrail/"
    input_format  = "com.amazon.emr.cloudtrail.CloudTrailInputFormat"
    output_format = "org.apache.hadoop.hive.ql.io.HiveIgnoreKeyTextOutputFormat"

    ser_de_info {
      serialization_library = "com.amazon.emr.hive.serde.CloudTrailSerde"
    }

    columns {
      name = "eventversion"      ; type = "string"
    }
    columns {
      name = "useridentity"      ; type = "struct<type:string,principalid:string,arn:string,accountid:string,invokedby:string,accesskeyid:string,userName:string,sessioncontext:struct<attributes:struct<mfaauthenticated:string,creationdate:string>,sessionissuer:struct<type:string,principalId:string,arn:string,accountId:string,userName:string>>>"
    }
    columns { name = "eventtime"          ; type = "string" }
    columns { name = "eventsource"        ; type = "string" }
    columns { name = "eventname"          ; type = "string" }
    columns { name = "awsregion"          ; type = "string" }
    columns { name = "sourceipaddress"    ; type = "string" }
    columns { name = "useragent"          ; type = "string" }
    columns { name = "errorcode"          ; type = "string" }
    columns { name = "errormessage"       ; type = "string" }
    columns { name = "requestparameters" ; type = "string" }
    columns { name = "responseelements"  ; type = "string" }
    columns { name = "requestid"          ; type = "string" }
    columns { name = "eventid"            ; type = "string" }
    columns { name = "eventtype"          ; type = "string" }
    columns { name = "accountid"          ; type = "string" }
    columns { name = "readonly"           ; type = "boolean" }
  }
}
```

---

## Athena Queries for Security Investigations

```sql
-- Find all API calls from a specific IP in last 7 days
SELECT eventtime, useridentity.arn, eventsource, eventname, sourceipaddress, errorcode
FROM cloudtrail_logs.cloudtrail_logs
WHERE year = 2026 AND month = 5
  AND sourceipaddress = '203.0.113.42'
ORDER BY eventtime DESC;

-- Root account usage
SELECT eventtime, eventsource, eventname, sourceipaddress, awsregion
FROM cloudtrail_logs.cloudtrail_logs
WHERE year = 2026 AND month >= 4
  AND useridentity.type = 'Root'
ORDER BY eventtime DESC;

-- IAM changes in last 24 hours
SELECT eventtime, useridentity.arn, eventname, requestparameters
FROM cloudtrail_logs.cloudtrail_logs
WHERE year = 2026 AND month = 5 AND day >= 7
  AND eventsource = 'iam.amazonaws.com'
  AND eventname IN ('CreateUser','AttachUserPolicy','CreateAccessKey','UpdateAssumeRolePolicy')
ORDER BY eventtime DESC;

-- Failed authentication attempts
SELECT sourceipaddress, COUNT(*) as fail_count, MIN(eventtime) as first_seen, MAX(eventtime) as last_seen
FROM cloudtrail_logs.cloudtrail_logs
WHERE year = 2026 AND month = 5
  AND errorcode IN ('AccessDenied','UnauthorizedOperation','Client.UnauthorizedOperation')
GROUP BY sourceipaddress
ORDER BY fail_count DESC
LIMIT 20;

-- S3 bucket policy changes
SELECT eventtime, useridentity.arn, eventname, requestparameters
FROM cloudtrail_logs.cloudtrail_logs
WHERE year = 2026 AND month = 5
  AND eventsource = 's3.amazonaws.com'
  AND eventname IN ('PutBucketPolicy','DeleteBucketPolicy','PutBucketAcl')
ORDER BY eventtime DESC;
```

---

## CloudWatch Metric Filters (CIS Benchmark)

```hcl
locals {
  cis_filters = {
    root_account_usage = {
      pattern = "{$.userIdentity.type=\"Root\" && $.userIdentity.invokedBy NOT EXISTS && $.eventType !=\"AwsServiceEvent\"}"
      metric  = "RootAccountUsage"
    }
    iam_policy_change = {
      pattern = "{($.eventName=DeleteGroupPolicy)||($.eventName=DeleteRolePolicy)||($.eventName=DeleteUserPolicy)||($.eventName=PutGroupPolicy)||($.eventName=PutRolePolicy)||($.eventName=PutUserPolicy)||($.eventName=CreatePolicy)||($.eventName=DeletePolicy)||($.eventName=CreatePolicyVersion)||($.eventName=DeletePolicyVersion)||($.eventName=SetDefaultPolicyVersion)||($.eventName=AttachRolePolicy)||($.eventName=DetachRolePolicy)||($.eventName=AttachUserPolicy)||($.eventName=DetachUserPolicy)||($.eventName=AttachGroupPolicy)||($.eventName=DetachGroupPolicy)}"
      metric  = "IAMPolicyChange"
    }
    cloudtrail_config_change = {
      pattern = "{($.eventName=CreateTrail)||($.eventName=UpdateTrail)||($.eventName=DeleteTrail)||($.eventName=StartLogging)||($.eventName=StopLogging)}"
      metric  = "CloudTrailConfigChange"
    }
    console_auth_failure = {
      pattern = "{($.eventName=ConsoleLogin)&&($.errorMessage=\"Failed authentication\")}"
      metric  = "ConsoleAuthFailure"
    }
    cmk_deletion = {
      pattern = "{($.eventSource=kms.amazonaws.com)&&(($.eventName=DisableKey)||($.eventName=ScheduleKeyDeletion))}"
      metric  = "CMKDeletion"
    }
    s3_bucket_policy_change = {
      pattern = "{($.eventSource=s3.amazonaws.com)&&(($.eventName=PutBucketAcl)||($.eventName=PutBucketPolicy)||($.eventName=PutBucketCors)||($.eventName=PutBucketLifecycle)||($.eventName=PutBucketReplication)||($.eventName=DeleteBucketPolicy)||($.eventName=DeleteBucketCors)||($.eventName=DeleteBucketLifecycle)||($.eventName=DeleteBucketReplication))}"
      metric  = "S3BucketPolicyChange"
    }
    sg_change = {
      pattern = "{($.eventName=AuthorizeSecurityGroupIngress)||($.eventName=AuthorizeSecurityGroupEgress)||($.eventName=RevokeSecurityGroupIngress)||($.eventName=RevokeSecurityGroupEgress)||($.eventName=CreateSecurityGroup)||($.eventName=DeleteSecurityGroup)}"
      metric  = "SecurityGroupChange"
    }
  }
}

resource "aws_cloudwatch_log_metric_filter" "cis" {
  for_each = local.cis_filters

  name           = each.key
  pattern        = each.value.pattern
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  metric_transformation {
    name      = each.value.metric
    namespace = "CISBenchmark"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "cis" {
  for_each = local.cis_filters

  alarm_name          = "cis-${each.key}"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = each.value.metric
  namespace           = "CISBenchmark"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
  treat_missing_data  = "notBreaching"
}
```

---

## Verify Log Integrity

```bash
# Validate CloudTrail log file integrity
aws cloudtrail validate-logs \
  --trail-arn arn:aws:cloudtrail:us-east-1:123456789012:trail/organization-trail \
  --start-time 2026-05-01T00:00:00Z \
  --end-time 2026-05-08T00:00:00Z \
  --verbose

# Output: "Digest file valid." for each hour — any failure indicates tampering
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| Management events (first trail) | Free |
| Additional trails (management events) | $2.00/100k events |
| Data events (S3/Lambda) | $0.10/100k events |
| Insights events | $0.35/100k events |
| CloudWatch Logs ingestion | $0.50/GB |
| S3 storage (Standard) | $0.023/GB/month |
| Glacier (after 1 year) | $0.004/GB/month |
| Athena queries | $5.00/TB scanned |

**Cost optimization:**
- Partition projection in Athena — never scan full table; always filter by year/month/day
- Lifecycle policy — move logs to STANDARD_IA at 90 days, GLACIER at 365 days
- Compress Athena results in S3 — partition by account+region+date
- Only enable data events on sensitive buckets, not `arn:aws:s3:::*`

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Per-account trails instead of org trail | Create one organization trail in management account |
| CloudTrail bucket in same account | Use dedicated Log Archive account |
| No log file integrity validation | Set `enable_log_file_validation = true` |
| SSE-S3 instead of CMK | Use KMS CMK for full audit trail on log access |
| No lifecycle policy on log bucket | Logs grow unbounded; set lifecycle to GLACIER at 365 days |
| Athena full table scan | Always use partition filters (year/month/day/region) |
| No CIS Benchmark metric filters | Missing compliance monitoring |

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
