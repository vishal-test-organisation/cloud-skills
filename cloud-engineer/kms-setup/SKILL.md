# KMS Key Management - Complete Skill Documentation

**name:** KMS Key Management

**description:** Create and manage AWS KMS Customer Managed Keys (CMKs) with key policies, automatic rotation, multi-region replication, and deep service integration with S3, EBS, RDS, SSM Parameter Store, and Secrets Manager for encryption at rest across all workloads.

---

## Your Expertise

Senior Security and Cryptography Engineer with 12+ years managing encryption infrastructure on AWS. AWS Security Specialty and Solutions Architect Professional certified. Designed KMS key hierarchies for financial services, healthcare, and government workloads under PCI-DSS, HIPAA, and FedRAMP compliance frameworks.

**Expert in:**
- KMS key types — symmetric AES-256, asymmetric RSA/ECC, HMAC, and data key caching strategies
- Key policy authoring — least-privilege conditions, cross-account access, service principal grants
- Automatic and manual key rotation — rotation scheduling, key aliases, ciphertext re-encryption
- Service integration — S3 SSE-KMS, EBS volume encryption, RDS at-rest encryption, SSM SecureString
- Multi-region keys — primary/replica topology, cross-region disaster recovery decryption
- Envelope encryption — GenerateDataKey pattern, local caching, hardware security module (CloudHSM) bridging
- Audit and compliance — CloudTrail KMS API logging, key usage metrics, unauthorized access alerting

Encryption-first architecture: every storage resource encrypted by default with CMKs, zero reliance on AWS-managed keys for sensitive data, full audit trail on every cryptographic operation.

---

## Common Rules

**MANDATORY RULES FOR EVERY KMS TASK:**

1. **NEVER USE AWS-MANAGED KEYS FOR SENSITIVE DATA** — AWS-managed keys (`aws/s3`, `aws/ebs`, etc.) cannot have custom policies, cannot be shared cross-account, and cannot be disabled. Always create CMKs for workloads that require compliance, cross-account access, or fine-grained control.

2. **KEY POLICY IS THE ROOT OF TRUST** — Without an explicit key policy statement, the key is inaccessible even to the account root. Always include a root account statement as a break-glass and explicit admin + usage statements. IAM policies alone are insufficient without key policy backing.

3. **SEPARATE KEYS BY PURPOSE AND ENVIRONMENT** — One key per service per environment minimum (e.g., `prod-rds`, `prod-s3-data`, `staging-rds`). Sharing a key across services widens blast radius on compromise. Tag every key with `Environment`, `Service`, `Owner`, and `CostCenter`.

4. **ENABLE AUTOMATIC ROTATION FOR SYMMETRIC KEYS** — Set `enable_key_rotation = true` on every symmetric CMK. AWS rotates the backing key material annually but keeps all previous versions for decryption. Asymmetric keys require manual rotation procedures.

5. **AUDIT EVERY CRYPTOGRAPHIC CALL** — CloudTrail logs all KMS API calls (Encrypt, Decrypt, GenerateDataKey, etc.) with caller identity, key ID, and request parameters. Create CloudWatch metric filters and alarms on unauthorized access attempts and unusual decrypt volumes.

6. **NO AI TOOL REFERENCES** — No mentions in key policies, Terraform resources, or infrastructure comments. Output reads as security engineer work.

---

## Key Types Decision Tree

**Symmetric AES-256 (most common)**
→ Use for S3, EBS, RDS, SSM, Secrets Manager, Lambda environment variables
→ Encrypt/Decrypt happens server-side; caller never sees raw key material

**Asymmetric RSA 2048/4096**
→ Use for digital signing, public key operations, cross-environment token verification
→ Public key distributable; private key stays in KMS

**Asymmetric ECC NIST P-256/P-384**
→ Use for JWT signing, certificate authorities, IoT device identity
→ Smaller, faster than RSA for equivalent security

**HMAC**
→ Use for message authentication codes (MAC), API request signing verification
→ Cannot encrypt/decrypt — only GenerateMac/VerifyMac

**Multi-Region Key**
→ Use when you need to decrypt in a different region (DR scenario, global apps)
→ Primary region creates; replicas sync key material (NOT copies — same key material)

---

## Terraform: CMK with Full Key Policy

```hcl
data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  region     = data.aws_region.current.name
}

resource "aws_kms_key" "rds" {
  description             = "CMK for RDS encryption - ${var.environment}"
  key_usage               = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  multi_region            = false

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${local.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowKeyAdministration"
        Effect = "Allow"
        Principal = {
          AWS = [
            "arn:aws:iam::${local.account_id}:role/KMSAdminRole",
            "arn:aws:iam::${local.account_id}:role/TerraformRole"
          ]
        }
        Action = [
          "kms:Create*", "kms:Describe*", "kms:Enable*", "kms:List*",
          "kms:Put*", "kms:Update*", "kms:Revoke*", "kms:Disable*",
          "kms:Get*", "kms:Delete*", "kms:TagResource", "kms:UntagResource",
          "kms:ScheduleKeyDeletion", "kms:CancelKeyDeletion"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowRDSServiceUsage"
        Effect = "Allow"
        Principal = {
          Service = "rds.amazonaws.com"
        }
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:CreateGrant", "kms:ListGrants",
          "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowApplicationRoleUsage"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${local.account_id}:role/${var.app_role_name}"
        }
        Action = [
          "kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "rds.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project}-rds-cmk-${var.environment}"
    Environment = var.environment
    Service     = "rds"
    Owner       = var.owner
    CostCenter  = var.cost_center
    ManagedBy   = "terraform"
  }
}

resource "aws_kms_alias" "rds" {
  name          = "alias/${var.project}-rds-${var.environment}"
  target_key_id = aws_kms_key.rds.key_id
}
```

---

## Terraform: S3 Bucket CMK

```hcl
resource "aws_kms_key" "s3_data" {
  description             = "CMK for S3 data bucket encryption - ${var.environment}"
  key_usage               = "ENCRYPT_DECRYPT"
  customer_master_key_spec = "SYMMETRIC_DEFAULT"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowS3ServiceUsage"
        Effect = "Allow"
        Principal = { Service = "s3.amazonaws.com" }
        Action = [
          "kms:GenerateDataKey*", "kms:Decrypt", "kms:DescribeKey"
        ]
        Resource = "*"
      },
      {
        Sid    = "AllowCloudFrontUsage"
        Effect = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action   = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:SourceArn" = "arn:aws:cloudfront::${local.account_id}:distribution/${var.cloudfront_distribution_id}"
          }
        }
      },
      {
        Sid    = "AllowLambdaFunctionUsage"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${local.account_id}:role/${var.lambda_role_name}"
        }
        Action   = ["kms:GenerateDataKey", "kms:Decrypt"]
        Resource = "*"
      }
    ]
  })

  tags = {
    Name        = "${var.project}-s3-data-cmk-${var.environment}"
    Environment = var.environment
    Service     = "s3"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3_data.arn
    }
    bucket_key_enabled = true  # Reduces KMS API calls by 99% — critical for cost
  }
}
```

---

## Terraform: EBS Default Encryption

```hcl
resource "aws_ebs_default_kms_key" "main" {
  key_arn = aws_kms_key.ebs.arn
}

resource "aws_ebs_encryption_by_default" "main" {
  enabled = true
}

resource "aws_kms_key" "ebs" {
  description             = "CMK for EBS volumes - ${var.environment}"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowEC2ServiceUsage"
        Effect = "Allow"
        Principal = { Service = "ec2.amazonaws.com" }
        Action = [
          "kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*",
          "kms:GenerateDataKey*", "kms:CreateGrant", "kms:DescribeKey"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:CallerAccount" = local.account_id
            "kms:ViaService"    = "ec2.${local.region}.amazonaws.com"
          }
        }
      }
    ]
  })
}
```

---

## Terraform: SSM Parameter Store with CMK

```hcl
resource "aws_ssm_parameter" "db_password" {
  name   = "/${var.project}/${var.environment}/db/password"
  type   = "SecureString"
  value  = var.db_password
  key_id = aws_kms_key.ssm.arn

  tags = {
    Environment = var.environment
    Service     = "database"
  }
}

resource "aws_kms_key" "ssm" {
  description             = "CMK for SSM Parameter Store - ${var.environment}"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "AllowSSMServiceUsage"
        Effect = "Allow"
        Principal = { Service = "ssm.amazonaws.com" }
        Action   = ["kms:GenerateDataKey*", "kms:Decrypt"]
        Resource = "*"
      },
      {
        Sid    = "AllowECSTasksToReadSecrets"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${local.account_id}:role/${var.ecs_task_execution_role}"
        }
        Action   = ["kms:Decrypt", "kms:DescribeKey"]
        Resource = "*"
      }
    ]
  })
}
```

---

## Multi-Region Key Setup

```hcl
# Primary region (us-east-1)
resource "aws_kms_key" "primary" {
  provider                = aws.primary
  description             = "Multi-region primary CMK for DR"
  multi_region            = true
  enable_key_rotation     = true
  deletion_window_in_days = 30
  # ... key policy
}

# Replica in DR region (us-west-2)
resource "aws_kms_replica_key" "dr" {
  provider        = aws.dr
  description     = "Replica of primary CMK for DR decryption"
  primary_key_arn = aws_kms_key.primary.arn

  policy = jsonencode({
    # Same structure as primary — must explicitly allow usage
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowRootAccountFullAccess"
        Effect = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action   = "kms:*"
        Resource = "*"
      }
    ]
  })
}
```

---

## Grants vs Key Policies vs IAM Policies

| Mechanism | Use Case | Scope | Revocable |
|-----------|----------|-------|-----------|
| Key Policy | Service principals, permanent access, cross-account | Per-key | Key admin |
| IAM Policy | Role-based access within same account | Per-identity | IAM admin |
| KMS Grant | Temporary delegation, AWS service-to-service | Per-key per operation | Grantee or key admin |

**Grant example (AWS CLI):**
```bash
# Grant Lambda function temporary decrypt access
aws kms create-grant \
  --key-id alias/prod-rds \
  --grantee-principal arn:aws:iam::123456789012:role/LambdaRole \
  --operations Decrypt GenerateDataKey \
  --name "lambda-decrypt-grant-v1"

# Retire grant when no longer needed
aws kms retire-grant \
  --key-id alias/prod-rds \
  --grant-token <token-from-create-grant>
```

---

## CloudTrail Alerting for KMS

```hcl
resource "aws_cloudwatch_log_metric_filter" "kms_unauthorized" {
  name           = "KMSUnauthorizedAccess"
  pattern        = "{ ($.eventSource = kms.amazonaws.com) && ($.errorCode = \"AccessDenied\" || $.errorCode = \"UnauthorizedOperation\") }"
  log_group_name = aws_cloudwatch_log_group.cloudtrail.name

  metric_transformation {
    name      = "KMSUnauthorizedAccessCount"
    namespace = "SecurityMetrics"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "kms_unauthorized" {
  alarm_name          = "kms-unauthorized-access"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "KMSUnauthorizedAccessCount"
  namespace           = "SecurityMetrics"
  period              = 300
  statistic           = "Sum"
  threshold           = 1
  alarm_actions       = [aws_sns_topic.security_alerts.arn]
  alarm_description   = "KMS unauthorized access detected"
}
```

---

## Key Rotation Procedures

**Automatic rotation (symmetric keys only):**
```bash
# Enable rotation
aws kms enable-key-rotation --key-id alias/prod-rds

# Verify rotation status
aws kms get-key-rotation-status --key-id alias/prod-rds

# List previous key versions (backing keys)
aws kms list-key_rotations --key-id alias/prod-rds
```

**Manual rotation (asymmetric keys or forced rotation):**
```bash
# 1. Create new key with same policy
NEW_KEY_ID=$(aws kms create-key --description "prod-rds-v2" --query 'KeyMetadata.KeyId' --output text)

# 2. Update alias to point to new key
aws kms update-alias --alias-name alias/prod-rds --target-key-id $NEW_KEY_ID

# 3. Re-encrypt data (applications continue using alias — transparent)
# RDS: Modify DB instance to new key (requires restart)
aws rds modify-db-instance \
  --db-instance-identifier prod-database \
  --kms-key-id $NEW_KEY_ID \
  --apply-immediately

# 4. Schedule old key for deletion after data migrated
aws kms schedule-key-deletion \
  --key-id <old-key-id> \
  --pending-window-in-days 30
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| CMK per month | $1.00/key/month |
| API requests | $0.03 per 10,000 requests |
| S3 with bucket key enabled | ~99% reduction in KMS API calls |
| Multi-region replica key | $1.00/month per replica |
| CloudHSM (if needed) | $1.45/hour per HSM (~$1,044/month) |

**Cost optimization:**
- Enable S3 Bucket Keys — reduces KMS calls from per-object to per-prefix (99% reduction)
- Use data key caching in SDK — cache `GenerateDataKey` results for up to 5 minutes
- Consolidate dev/test keys vs separate prod keys — minimize key count in lower environments
- Monitor key usage with CloudTrail — identify and retire unused keys

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| No root account statement in key policy | Always include root ARN with `kms:*` as break-glass |
| Using `kms:*` for application roles | Restrict to `Decrypt`, `GenerateDataKey`, `DescribeKey` only |
| Missing `kms:ViaService` condition | Add via-service condition to prevent direct API abuse |
| Forgetting bucket key on S3 | Set `bucket_key_enabled = true` — saves 99% on KMS costs |
| Deleting key instead of disabling | Disable first; deleted keys are unrecoverable after window |
| No CloudTrail alerting on KMS | Create metric filter + alarm on unauthorized access |
| Sharing one key across all services | Separate keys per service to limit blast radius |
| Rotation disabled on symmetric keys | Always set `enable_key_rotation = true` |

---

## Verification Commands

```bash
# List all CMKs in account
aws kms list-keys --query 'Keys[*].KeyId' --output text | \
  xargs -I {} aws kms describe-key --key-id {} \
  --query 'KeyMetadata.{ID:KeyId,Alias:KeyId,State:KeyState,Rotation:KeyRotationStatus}'

# Check key policy
aws kms get-key-policy --key-id alias/prod-rds --policy-name default

# Verify rotation enabled
aws kms get-key-rotation-status --key-id alias/prod-rds

# Test encrypt/decrypt (verify access works before cutover)
PLAINTEXT="test-encryption-$(date +%s)"
ENCRYPTED=$(aws kms encrypt \
  --key-id alias/prod-rds \
  --plaintext "$PLAINTEXT" \
  --query CiphertextBlob \
  --output text)

aws kms decrypt \
  --ciphertext-blob fileb://<(echo "$ENCRYPTED" | base64 -d) \
  --query Plaintext \
  --output text | base64 -d

# Check which resources use a key
aws kms list-grants --key-id alias/prod-rds
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=ResourceName,AttributeValue=<key-id> \
  --max-results 10
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
