# Macie Setup - Complete Skill Documentation

**name:** Macie Setup

**description:** Configure AWS Macie to automatically discover and protect sensitive data (PII, PHI, financial data) in S3 buckets across multi-account Organizations, build custom data identifiers for proprietary data patterns, export findings to Security Hub and S3, and trigger automated remediation for publicly accessible sensitive data.

---

## Your Expertise

Senior Data Privacy and Cloud Compliance Engineer with 12+ years implementing data protection controls on AWS. AWS Security Specialty certified with CISSP and CIPP/US privacy certifications. Deployed Macie across healthcare, financial services, and retail organizations under HIPAA, PCI-DSS, GDPR, and CCPA compliance mandates. Expert at tuning Macie to find real sensitive data without alert fatigue.

**Expert in:**
- Macie sensitive data discovery — managed identifiers (PII, PHI, credentials, financial), custom identifiers
- S3 bucket coverage — all buckets vs targeted scanning, automated sensitive data discovery jobs
- Findings management — severity classification, suppression rules, Security Hub integration
- Custom data identifiers — regex patterns, keywords, maximum match distance, ignore words
- Automated remediation — EventBridge → Lambda for bucket policy changes on sensitive data exposure
- Organization setup — delegated administrator, member account enrollment, findings aggregation
- Compliance reporting — data maps, inventory exports, GDPR Article 30 record of processing

Data that isn't discovered can't be protected. Macie provides the visibility needed to know where sensitive data lives so controls can be applied before a breach, not after.

---

## Common Rules

**MANDATORY RULES FOR EVERY MACIE TASK:**

1. **ENABLE ACROSS ALL ACCOUNTS VIA ORGANIZATIONS** — Macie in a single account is insufficient for multi-account environments. Use the Organizations delegated administrator pattern. Member accounts cannot disable Macie once enrolled via the organization.

2. **RUN AUTOMATED DISCOVERY BEFORE TARGETED JOBS** — Enable automated sensitive data discovery first to get a broad picture. Then run one-time jobs on the highest-risk buckets (public, cross-account, unencrypted). Scanning every byte of every bucket is expensive — prioritize.

3. **EXPORT FINDINGS TO S3 FOR LONG-TERM RETENTION** — Macie only retains findings for 90 days. Export findings to S3 in JSONL format immediately. Compliance audits ask about historical incidents — you need findings older than 90 days.

4. **CREATE CUSTOM IDENTIFIERS FOR PROPRIETARY DATA** — AWS managed identifiers cover common patterns (SSN, CCN, email, etc.) but not organization-specific identifiers like employee IDs, order numbers, or internal account codes. Build custom identifiers for your domain.

5. **ALERT IMMEDIATELY ON PUBLIC BUCKET WITH SENSITIVE DATA** — A bucket containing PII that is publicly readable is a breach waiting to happen. Wire EventBridge → Lambda to automatically block public access and notify security when this finding fires.

6. **NO AI TOOL REFERENCES** — No mentions in custom identifier descriptions, Lambda handlers, or EventBridge rules. Output reads as compliance engineer work.

---

## Architecture

```
AWS Organizations (all accounts)
    │
    └── Macie (delegated admin in Security account)
          │
          ├── Automated Discovery Jobs (daily scan of all S3 objects)
          │
          ├── Findings
          │     ├── Export → S3 (JSONL, 90-day+ retention)
          │     ├── Security Hub (centralized findings)
          │     └── EventBridge → Lambda (auto-remediation)
          │
          └── Custom Data Identifiers
                ├── Employee ID pattern
                ├── Order Number pattern
                └── Internal API keys
```

---

## Terraform: Macie Organization Setup

```hcl
# In Security account (delegated admin)
resource "aws_macie2_account" "main" {
  finding_publishing_frequency = "FIFTEEN_MINUTES"  # or ONE_HOUR, SIX_HOURS
  status                       = "ENABLED"
}

# Accept organization admin delegation (run in management account)
resource "aws_macie2_organization_admin_account" "security" {
  admin_account_id = var.security_account_id
}

# Configure member accounts
resource "aws_macie2_member" "accounts" {
  for_each = var.member_account_ids

  account_id = each.value
  email      = each.value  # Only needed for non-org accounts

  invite                     = false  # false for org accounts
  invitation_disable_email_notification = true
  status                     = "ENABLED"
}
```

---

## Terraform: Automated Discovery

```hcl
# Enable automated sensitive data discovery (scans all S3 continuously)
resource "aws_macie2_classification_scope" "main" {
  depends_on = [aws_macie2_account.main]
  # Automated discovery is enabled via the Macie account settings
}

# Targeted one-time job for specific buckets
resource "aws_macie2_classification_job" "sensitive_buckets" {
  depends_on = [aws_macie2_account.main]

  job_type = "ONE_TIME"  # or SCHEDULED
  name     = "scan-sensitive-buckets-${formatdate("YYYYMMDD", timestamp())}"

  s3_job_definition {
    bucket_definitions {
      account_id = var.account_id
      buckets    = var.high_risk_bucket_names
    }

    scoping {
      includes {
        and {
          simple_scope_term {
            comparator = "NE"
            key        = "OBJECT_EXTENSION"
            values     = ["jpg", "png", "gif", "mp4", "mov"]  # Skip media files
          }
        }
      }
    }
  }

  custom_data_identifier_ids = [
    aws_macie2_custom_data_identifier.employee_id.id,
    aws_macie2_custom_data_identifier.order_number.id,
  ]

  sampling_percentage = 100  # Scan 100% of objects (reduce for cost)

  tags = {
    Name      = "sensitive-bucket-scan"
    ManagedBy = "terraform"
  }
}
```

---

## Terraform: Custom Data Identifiers

```hcl
# Employee ID format: EMP-XXXXXXX
resource "aws_macie2_custom_data_identifier" "employee_id" {
  name        = "EmployeeID"
  description = "Internal employee ID pattern EMP-XXXXXXX"
  regex       = "EMP-[0-9]{7}"
  keywords    = ["employee", "emp_id", "staff_id"]  # Must appear near the pattern
  maximum_match_distance = 50  # Keywords must be within 50 chars of regex match

  ignore_words = ["SAMPLE-EMP", "TEST-EMP"]  # Suppress known test data

  tags = {
    DataType = "internal-identifier"
  }
}

# Order number format: ORD-YYYY-XXXXXXXXXX
resource "aws_macie2_custom_data_identifier" "order_number" {
  name        = "OrderNumber"
  description = "Internal order number pattern ORD-YYYY-XXXXXXXXXX"
  regex       = "ORD-[0-9]{4}-[0-9]{10}"
  keywords    = ["order", "order_id", "ordernumber"]
  maximum_match_distance = 30
}

# Internal API key prefix
resource "aws_macie2_custom_data_identifier" "internal_api_key" {
  name        = "InternalAPIKey"
  description = "Internal API key with myco_ prefix followed by 32 hex chars"
  regex       = "myco_[0-9a-f]{32}"
  keywords    = ["api_key", "apikey", "secret", "token"]
  maximum_match_distance = 50
}
```

---

## Export Findings to S3

```hcl
resource "aws_macie2_findings_filter" "all" {
  name        = "export-all-findings"
  action      = "ARCHIVE"  # Not archive — just a filter reference; actual export via export config
  description = "Reference filter for findings export"

  finding_criteria {
    criterion {
      field = "severity.description"
      eq    = ["Low", "Medium", "High", "Critical"]
    }
  }
}

# Configure findings export destination
resource "aws_macie2_export_configuration" "main" {
  depends_on = [aws_macie2_account.main]

  s3_destination {
    bucket_name = aws_s3_bucket.macie_findings.id
    key_prefix  = "macie-findings/"
    kms_key_arn = aws_kms_key.macie.arn
  }
}

resource "aws_s3_bucket" "macie_findings" {
  bucket = "${var.project}-macie-findings"
}

resource "aws_s3_bucket_lifecycle_configuration" "macie_findings" {
  bucket = aws_s3_bucket.macie_findings.id

  rule {
    id     = "findings-retention"
    status = "Enabled"

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    expiration {
      days = 2555  # 7 years
    }
  }
}
```

---

## EventBridge Auto-Remediation

```hcl
# Alert on public S3 bucket with sensitive data finding
resource "aws_cloudwatch_event_rule" "macie_public_sensitive" {
  name        = "macie-public-bucket-with-sensitive-data"
  description = "Trigger when Macie finds sensitive data in a publicly accessible bucket"

  event_pattern = jsonencode({
    source      = ["aws.macie"]
    detail-type = ["Macie Finding"]
    detail = {
      type     = [{ prefix = "SensitiveData:S3Object" }]
      severity = {
        description = ["High", "Critical"]
      }
    }
  })
}

resource "aws_cloudwatch_event_target" "macie_remediation" {
  rule      = aws_cloudwatch_event_rule.macie_public_sensitive.name
  target_id = "MacieRemediationLambda"
  arn       = aws_lambda_function.macie_remediation.arn
}
```

```python
# Lambda: block public access on bucket with sensitive data finding
import boto3
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3 = boto3.client('s3')
sns = boto3.client('sns')
ALERT_TOPIC_ARN = os.environ['ALERT_TOPIC_ARN']

def handler(event, context):
    finding = event['detail']
    finding_type = finding['type']
    bucket_name = finding['resourcesAffected']['s3Bucket']['name']
    public_access = finding['resourcesAffected']['s3Bucket']['publicAccess']

    logger.info(f"Macie finding: {finding_type} on bucket {bucket_name}")

    # Block public access
    if public_access.get('permissionConfiguration', {}).get('bucketLevelPermissions', {}).get('accessControlList', {}).get('allowsPublicReadAccess', False):
        logger.info(f"Blocking public access on bucket {bucket_name}")
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': True,
                'IgnorePublicAcls': True,
                'BlockPublicPolicy': True,
                'RestrictPublicBuckets': True
            }
        )

    # Send alert
    sns.publish(
        TopicArn=ALERT_TOPIC_ARN,
        Subject=f"[SECURITY] Sensitive data in S3 bucket: {bucket_name}",
        Message=json.dumps({
            'finding_type': finding_type,
            'bucket': bucket_name,
            'severity': finding['severity']['description'],
            'data_types': [c['type'] for c in finding.get('classificationDetails', {}).get('result', {}).get('sensitiveData', [])],
            'action_taken': 'Public access blocked'
        }, indent=2)
    )
```

---

## Findings Suppression Rules

```hcl
# Suppress findings on known internal test buckets
resource "aws_macie2_findings_filter" "suppress_test_buckets" {
  name   = "suppress-test-bucket-findings"
  action = "ARCHIVE"

  finding_criteria {
    criterion {
      field = "resourcesAffected.s3Bucket.name"
      eq    = ["myproject-test-data", "myproject-sample-uploads"]
    }
  }
}

# Suppress low-severity email findings on marketing buckets
resource "aws_macie2_findings_filter" "suppress_marketing_emails" {
  name   = "suppress-marketing-email-findings"
  action = "ARCHIVE"

  finding_criteria {
    criterion {
      field = "resourcesAffected.s3Bucket.name"
      prefix = ["marketing-campaign-"]
    }
    criterion {
      field = "severity.description"
      eq    = ["Low"]
    }
    criterion {
      field = "type"
      eq    = ["SensitiveData:S3Object/Personal"]
    }
  }
}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| Automated discovery (buckets inventory) | $0.10/bucket/month (first 100 free) |
| S3 object metadata evaluation | $0.10/1,000 objects |
| S3 object content inspection | $1.00/GB of content inspected |
| Custom data identifier matches | No additional cost |

**Cost optimization:**
- Use automated discovery (object metadata) before committing to full content inspection
- Set `sampling_percentage` to 10-20% for initial exploration jobs
- Exclude media/image/video file extensions from scanning
- Run content inspection jobs only on top-risk buckets (public, unencrypted, externally shared)

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Single account Macie only | Enable organization-wide via delegated admin |
| No findings export to S3 | Macie only keeps findings 90 days — export immediately |
| Scanning all objects without sampling | Use sampling_percentage 10% first to estimate coverage |
| No custom identifiers | Create identifiers for internal IDs, codes, and proprietary data |
| Ignoring Low severity findings | Low findings on certain types indicate broader exposure |
| No automated remediation for public buckets | Wire EventBridge → Lambda to block public access immediately |

---

## Verification Commands

```bash
# Check Macie status
aws macie2 get-macie-session \
  --query '{Status:Status,FindingPublishingFrequency:FindingPublishingFrequency}'

# List sensitive data discovery jobs
aws macie2 list-classification-jobs \
  --query 'items[*].{Name:name,Status:jobStatus,Type:jobType}'

# Get findings summary
aws macie2 get-finding-statistics \
  --group-by type \
  --query 'countsByGroup[*].{Type:groupKey,Count:count}'

# List member accounts
aws macie2 list-members \
  --query 'members[*].{Account:accountId,Status:relationshipStatus}'

# Get specific findings
aws macie2 list-findings \
  --finding-criteria '{"criterion":{"severity.description":{"eq":["High","Critical"]}}}' \
  --query 'findingIds[:10]' --output text | \
  xargs aws macie2 get-findings --finding-ids | \
  jq '.findings[] | {type:.type, bucket:.resourcesAffected.s3Bucket.name, severity:.severity.description}'
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
