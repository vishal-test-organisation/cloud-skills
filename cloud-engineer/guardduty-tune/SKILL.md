# GuardDuty Tuning & Auto-Remediation - Complete Skill Documentation

**name:** GuardDuty Tuning & Auto-Remediation

**description:** Fine-tune AWS GuardDuty findings to reduce noise, suppress false positives with intelligent filters, build EventBridge-triggered auto-remediation workflows for high-severity threats, and integrate with Security Hub for centralized findings management across multi-account Organizations.

---

## Your Expertise

Senior Cloud Security Engineer with 12+ years running threat detection and incident response on AWS. AWS Security Specialty certified. Managed GuardDuty at scale across 50+ account Organizations, reduced false-positive rate from 60% to under 5% while maintaining detection coverage for real threats. Expert in distinguishing legitimate DevOps activity from actual compromise indicators.

**Expert in:**
- GuardDuty finding types — Recon, UnauthorizedAccess, CryptoCurrency, Trojan, Backdoor, Behavior, PenTest
- Suppression rule design — resource-specific, account-specific, finding-type-specific filters
- EventBridge integration — real-time finding routing to Lambda, SNS, Security Hub, JIRA
- Auto-remediation patterns — isolate compromised EC2, revoke IAM credentials, block IPs in NACLs/WAF
- Threat intelligence — custom threat lists, trusted IP lists, S3 malware protection, RDS protection
- Multi-account setup — delegated administrator, member account enrollment, cross-region aggregation
- Cost management — finding frequency, suppression to reduce noise, S3 protection scope tuning

Detection without tuning is just noise. Real security teams tune GuardDuty to alert only on genuine threats and automate the first 15 minutes of incident response.

---

## Common Rules

**MANDATORY RULES FOR EVERY GUARDDUTY TASK:**

1. **ENABLE IN ALL REGIONS, ALL ACCOUNTS** — GuardDuty is region-specific. Threats in unused regions are real attack vectors (attackers target dark regions). Enable organization-wide via delegated administrator with auto-enable for new accounts.

2. **NEVER SUPPRESS BY FINDING TYPE ALONE** — Suppressing `UnauthorizedAccess:IAMUser/ConsoleLoginSuccess.B` globally hides real attacks. Always scope suppressions by resource ARN, account ID, or specific condition combination.

3. **CONNECT TO SECURITY HUB** — GuardDuty alone has no aggregation across accounts. Security Hub provides normalized ASFF findings, cross-account aggregation, and compliance standard mapping. Enable both together.

4. **AUTOMATE RESPONSE FOR SEVERITY ≥ 7.0** — HIGH and CRITICAL findings warrant immediate automated response. Waiting for on-call engineers to check dashboards means attackers have 30+ minutes of uncontested access. Wire Lambda remediation for specific finding types.

5. **TRUSTED IP LISTS ARE NOT ALLOWLISTS** — Trusted IP lists suppress findings for that IP entirely (all finding types). Only use for your own infrastructure IPs (e.g., NAT gateways, bastion hosts, CI/CD runners). Never add broad CIDR ranges.

6. **NO AI TOOL REFERENCES** — No mentions in Lambda functions, EventBridge rules, or suppression rule descriptions. Output reads as security engineer work.

---

## Finding Severity Scale

| Severity | Score | Action |
|----------|-------|--------|
| Critical | 9.0–10.0 | Immediate auto-remediate + page on-call |
| High | 7.0–8.9 | Auto-remediate + notify security team |
| Medium | 4.0–6.9 | Create ticket + investigate within 24h |
| Low | 1.0–3.9 | Log + weekly review |

---

## Terraform: GuardDuty Org Setup (Delegated Admin)

```hcl
# In management account
resource "aws_guardduty_organization_admin_account" "security" {
  admin_account_id = var.security_account_id
}

# In security account (delegated admin)
resource "aws_guardduty_detector" "main" {
  enable = true

  datasources {
    s3_logs {
      auto_enable = true
    }
    kubernetes {
      audit_logs {
        enable = true
      }
    }
    malware_protection {
      scan_ec2_instance_with_findings {
        ebs_volumes {
          auto_enable = true
        }
      }
    }
  }

  finding_publishing_frequency = "FIFTEEN_MINUTES"  # SIX_HOURS for cost, FIFTEEN_MINUTES for detection speed

  tags = {
    Environment = "security"
    ManagedBy   = "terraform"
  }
}

resource "aws_guardduty_organization_configuration" "main" {
  auto_enable_organization_members = "ALL"  # NEW accounts auto-enrolled
  detector_id                      = aws_guardduty_detector.main.id

  datasources {
    s3_logs {
      auto_enable = true
    }
    kubernetes {
      audit_logs {
        enable = true
      }
    }
    malware_protection {
      scan_ec2_instance_with_findings {
        ebs_volumes {
          auto_enable = true
        }
      }
    }
  }
}
```

---

## Suppression Rules (Terraform)

```hcl
# Suppress known CI/CD scanner activity
resource "aws_guardduty_filter" "suppress_ci_recon" {
  name        = "suppress-ci-recon-findings"
  detector_id = aws_guardduty_detector.main.id
  action      = "ARCHIVE"  # ARCHIVE = suppress; NOOP = no action
  rank        = 1

  finding_criteria {
    criterion {
      field  = "type"
      equals = ["Recon:EC2/PortProbeUnprotectedPort"]
    }
    criterion {
      field  = "resource.instanceDetails.tags.key"
      equals = ["Role"]
    }
    criterion {
      field  = "resource.instanceDetails.tags.value"
      equals = ["CI-Scanner"]
    }
  }

  description = "Suppress port probe findings from CI scanner instances tagged Role=CI-Scanner"
}

# Suppress legitimate Terraform/CloudFormation IAM activity
resource "aws_guardduty_filter" "suppress_iac_iam" {
  name        = "suppress-iac-iam-policy-changes"
  detector_id = aws_guardduty_detector.main.id
  action      = "ARCHIVE"
  rank        = 2

  finding_criteria {
    criterion {
      field  = "type"
      equals = ["Policy:IAMUser/RootCredentialUsage"]
    }
    criterion {
      field  = "resource.accessKeyDetails.userType"
      equals = ["Root"]
    }
    criterion {
      field  = "service.action.awsApiCallAction.remoteIpDetails.ipAddressV4"
      equals = var.known_admin_ips
    }
  }

  description = "Suppress root API usage from known admin IP ranges"
}

# Suppress known pentesting tools in dev environment
resource "aws_guardduty_filter" "suppress_dev_pentest" {
  name        = "suppress-dev-pentest-findings"
  detector_id = aws_guardduty_detector.main.id
  action      = "ARCHIVE"
  rank        = 3

  finding_criteria {
    criterion {
      field  = "accountId"
      equals = [var.dev_account_id]
    }
    criterion {
      field  = "type"
      equals = [
        "PenTest:IAMUser/KaliLinux",
        "PenTest:IAMUser/ParrotLinux",
        "PenTest:IAMUser/PentooLinux"
      ]
    }
  }

  description = "Suppress pentest tool findings in dev account only"
}
```

---

## Trusted IP List

```hcl
resource "aws_s3_object" "trusted_ips" {
  bucket  = aws_s3_bucket.guardduty_lists.id
  key     = "trusted-ips.txt"
  content = join("\n", concat(
    var.nat_gateway_ips,    # Own NAT gateways
    var.bastion_host_ips,   # Bastion/jump hosts
    var.ci_runner_ips       # CI/CD runner IPs
  ))
}

resource "aws_guardduty_ipset" "trusted" {
  name        = "${var.project}-trusted-ips"
  detector_id = aws_guardduty_detector.main.id
  format      = "TXT"
  location    = "s3://${aws_s3_bucket.guardduty_lists.id}/trusted-ips.txt"
  activate    = true
}
```

---

## EventBridge Rule for High-Severity Findings

```hcl
resource "aws_cloudwatch_event_rule" "guardduty_high_severity" {
  name        = "guardduty-high-severity-findings"
  description = "Route GuardDuty HIGH and CRITICAL findings for auto-remediation"

  event_pattern = jsonencode({
    source      = ["aws.guardduty"]
    detail-type = ["GuardDuty Finding"]
    detail = {
      severity = [{ numeric = [">=", 7.0] }]
    }
  })
}

resource "aws_cloudwatch_event_target" "remediation_lambda" {
  rule      = aws_cloudwatch_event_rule.guardduty_high_severity.name
  target_id = "GuardDutyRemediationLambda"
  arn       = aws_lambda_function.guardduty_remediation.arn
}

resource "aws_cloudwatch_event_target" "security_sns" {
  rule      = aws_cloudwatch_event_rule.guardduty_high_severity.name
  target_id = "GuardDutySecuritySNS"
  arn       = aws_sns_topic.security_alerts.arn
}
```

---

## Auto-Remediation Lambda

```python
import boto3
import json
import logging
import os

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ec2 = boto3.client('ec2')
iam = boto3.client('iam')
guardduty = boto3.client('guardduty')

ISOLATION_SG_ID = os.environ['ISOLATION_SG_ID']

def handler(event, context):
    finding = event['detail']
    finding_type = finding['type']
    severity = finding['severity']
    account_id = finding['accountId']
    detector_id = finding['service']['detectorId']
    finding_id = finding['id']

    logger.info(f"Processing finding: {finding_type} severity={severity} account={account_id}")

    if finding_type.startswith('UnauthorizedAccess:IAMUser') or finding_type.startswith('Behavior:IAMUser'):
        remediate_iam_finding(finding)
    elif finding_type.startswith('UnauthorizedAccess:EC2') or finding_type.startswith('Backdoor:EC2'):
        remediate_ec2_finding(finding)
    elif finding_type.startswith('CryptoCurrency:EC2'):
        remediate_crypto_mining(finding)

    # Archive finding after remediation
    guardduty.archive_findings(
        DetectorId=detector_id,
        FindingIds=[finding_id]
    )

def remediate_iam_finding(finding):
    """Deactivate access key involved in suspicious activity."""
    try:
        access_key_id = finding['resource']['accessKeyDetails']['accessKeyId']
        username = finding['resource']['accessKeyDetails']['userName']
        logger.info(f"Deactivating access key {access_key_id} for user {username}")

        iam.update_access_key(
            UserName=username,
            AccessKeyId=access_key_id,
            Status='Inactive'
        )
        logger.info(f"Successfully deactivated key {access_key_id}")
    except Exception as e:
        logger.error(f"Failed to remediate IAM finding: {e}")
        raise

def remediate_ec2_finding(finding):
    """Isolate compromised EC2 instance by replacing security groups."""
    try:
        instance_id = finding['resource']['instanceDetails']['instanceId']
        logger.info(f"Isolating EC2 instance {instance_id}")

        response = ec2.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        original_sgs = [sg['GroupId'] for sg in instance['SecurityGroups']]

        # Tag instance with original SGs for forensics
        ec2.create_tags(
            Resources=[instance_id],
            Tags=[
                {'Key': 'GuardDuty:Isolated', 'Value': 'true'},
                {'Key': 'GuardDuty:OriginalSGs', 'Value': ','.join(original_sgs)},
                {'Key': 'GuardDuty:FindingType', 'Value': finding['type']}
            ]
        )

        # Replace all SGs with isolation SG (no inbound, no outbound)
        ec2.modify_instance_attribute(
            InstanceId=instance_id,
            Groups=[ISOLATION_SG_ID]
        )
        logger.info(f"Instance {instance_id} isolated. Original SGs: {original_sgs}")
    except Exception as e:
        logger.error(f"Failed to isolate EC2 instance: {e}")
        raise

def remediate_crypto_mining(finding):
    """Stop instance running crypto mining workloads."""
    try:
        instance_id = finding['resource']['instanceDetails']['instanceId']
        logger.info(f"Stopping crypto mining instance {instance_id}")
        ec2.stop_instances(InstanceIds=[instance_id])
    except Exception as e:
        logger.error(f"Failed to stop crypto mining instance: {e}")
        raise
```

---

## Finding Type Coverage Map

| Category | Key Finding Types | Default Action |
|----------|------------------|----------------|
| Reconnaissance | PortProbeUnprotectedPort, PortProbeEC2Instance | Alert only |
| IAM Compromise | InstanceCredentialExfiltration, ConsoleLoginSuccess.B | Deactivate key |
| EC2 Compromise | Backdoor:EC2/XORDDOS, UnauthorizedAccess:EC2/SSHBruteForce | Isolate instance |
| Crypto Mining | CryptoCurrency:EC2/BitcoinTool.B | Stop instance |
| Exfiltration | S3/MaliciousIPCaller, S3/TorIPCaller | Block IP in WAF |
| Persistence | Backdoor:Lambda/C2Activity | Delete Lambda version |

---

## Security Hub Integration

```hcl
resource "aws_securityhub_account" "main" {}

resource "aws_securityhub_product_subscription" "guardduty" {
  depends_on  = [aws_securityhub_account.main]
  product_arn = "arn:aws:securityhub:${data.aws_region.current.name}::product/aws/guardduty"
}

resource "aws_securityhub_standards_subscription" "cis" {
  depends_on    = [aws_securityhub_account.main]
  standards_arn = "arn:aws:securityhub:::ruleset/cis-aws-foundations-benchmark/v/1.4.0"
}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| CloudTrail analysis | $4.00/1M events |
| DNS log analysis | $1.00/1M DNS queries |
| S3 data events analysis | $0.80/1M events |
| EKS audit log analysis | $2.00/1M log events |
| Malware protection (EBS) | $0.13/GB scanned |

**Cost optimization:**
- Set `finding_publishing_frequency = "SIX_HOURS"` in dev (reduces CloudTrail analysis frequency)
- Disable S3 data events on buckets with known high-volume legitimate access
- Use suppression rules aggressively in dev accounts to avoid false positive analysis cost
- Malware scanning only triggers on suspicious findings — not continuous scan

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Only enabling GuardDuty in primary region | Enable all regions via Organizations |
| Suppressing entire finding types | Always scope suppressions by resource/account |
| No auto-remediation for HIGH findings | Wire EventBridge → Lambda for severity ≥ 7.0 |
| Not integrating with Security Hub | Missing cross-account aggregation and compliance mapping |
| Trusted IP list with large CIDR blocks | Only add specific /32 IPs — never /16 or /8 |
| Not archiving findings after remediation | Leaves noise in active findings dashboard |
| Remediation Lambda missing error handling | Unhandled errors leave instances unprotected |

---

## Verification Commands

```bash
# List active (unarchived) findings by severity
aws guardduty list-findings \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text) \
  --finding-criteria '{"Criterion":{"severity":{"Gte":7.0},"service.archived":{"Eq":["false"]}}}' \
  --query 'FindingIds' --output text | \
  xargs aws guardduty get-findings \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text) \
  --findings | jq '.Findings[] | {type:.Type, severity:.Severity, account:.AccountId}'

# Check suppression rules
aws guardduty list-filters \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text)

# Check member accounts enrollment
aws guardduty list-members \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text) \
  --query 'Members[*].{Account:AccountId,Status:RelationshipStatus}'

# Get finding statistics
aws guardduty get-findings-statistics \
  --detector-id $(aws guardduty list-detectors --query 'DetectorIds[0]' --output text) \
  --finding-statistic-types COUNT_BY_SEVERITY
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
