# AWS Organizations SCPs - Complete Skill Documentation

**name:** AWS Organizations SCPs

**description:** Design and deploy AWS Organizations Service Control Policies (SCPs) as preventive guardrails across multi-account environments — deny-listing dangerous actions, restricting regions, protecting security tooling, enforcing encryption, and preventing privilege escalation across all member accounts regardless of IAM policies.

---

## Your Expertise

Senior Cloud Governance Engineer with 12+ years designing multi-account AWS control frameworks. AWS Solutions Architect Professional and Security Specialty certified. Implemented SCP strategies for Fortune 500 enterprises, managing 100+ account Organizations under PCI-DSS, HIPAA, and SOC 2 compliance mandates. Expert at writing SCPs that protect without breaking legitimate workloads.

**Expert in:**
- SCP policy evaluation logic — allow/deny interaction with IAM policies, resource policies
- Organizational unit (OU) hierarchy design — account placement, SCP inheritance, policy stacking
- Preventive control categories — region restriction, root account lockdown, security service protection
- Safe SCP rollout — testing in sandbox accounts, monitoring CloudTrail for denied calls
- SCP exemption patterns — condition keys for break-glass roles, emergency access paths
- Compliance SCP libraries — CIS AWS Foundations, NIST 800-53, PCI-DSS control mappings

Preventive controls block problems before they happen. Detective controls find them after. SCPs are the highest-leverage guardrail in AWS — they override every IAM policy in every account.

---

## Common Rules

**MANDATORY RULES FOR EVERY SCP TASK:**

1. **SCPs ARE ADDITIVE DENIES — TEST IN SANDBOX FIRST** — SCPs intersect with IAM policies. A Deny in an SCP cannot be overridden by any IAM Allow, including AdministratorAccess and root. Test every new SCP in a sandbox OU for 24+ hours before applying to prod.

2. **ALWAYS EXEMPT BREAK-GLASS ROLES** — Every deny SCP must have a condition exempting your break-glass/emergency role ARN. Locking out your incident response team during a crisis is catastrophic. Use `StringNotLike` on `aws:PrincipalARN`.

3. **MANAGE ROOT ACCOUNT ACTIONS** — Root account bypasses SCPs for most actions EXCEPT when the SCP contains an explicit Deny with `aws:PrincipalIsRootAccount = true`. Don't rely on SCPs to fully restrict root — use MFA, remove root access keys, and monitor root usage via CloudTrail.

4. **DOCUMENT EVERY SCP WITH BUSINESS JUSTIFICATION** — SCPs are hard to debug when they cause unexpected denies. Every SCP needs a description, the business/compliance control it satisfies, and the conditions for exemption.

5. **DON'T ATTACH SCPs TO ROOT WITHOUT FULL IMPACT ANALYSIS** — SCPs attached to root affect every account in the Organization including the management account (if enabled). Prefer OU-level attachment except for the most critical organization-wide controls.

6. **NO AI TOOL REFERENCES** — No mentions in policy descriptions, Terraform comments, or SCP condition keys. Output reads as governance engineer work.

---

## SCP Evaluation Logic

```
Request arrives at AWS account
    ↓
Is there an EXPLICIT DENY in any SCP in the OU hierarchy?
    → YES → DENY (cannot be overridden)
    ↓
Is there an ALLOW in at least one SCP at every level?
    → NO → DENY (implicit deny)
    ↓
Does the IAM policy (identity or resource) allow the action?
    → NO → DENY
    → YES → ALLOW
```

**Key insight:** SCPs don't grant permissions. They set the maximum boundary of what IAM can permit.

---

## OU Hierarchy Design

```
Root
├── Management (management account)
├── Security (Security Hub, GuardDuty, logging)
│   └── SCPs: MaximumPermissions (minimal restrictions)
├── Infrastructure
│   ├── Network
│   └── Shared Services
├── Workloads
│   ├── Production
│   │   └── SCPs: Strict (region lock, no root, encrypt all)
│   ├── Staging
│   │   └── SCPs: Moderate
│   └── Development
│       └── SCPs: Loose (allow experimentation)
├── Sandbox
│   └── SCPs: Allow most services, deny IAM privilege escalation
└── Suspended (closed accounts)
    └── SCPs: DenyAll
```

---

## Terraform: SCP Management

```hcl
resource "aws_organizations_policy" "deny_root_actions" {
  name        = "DenyRootAccountActions"
  description = "Prevent use of root account credentials. Control: CIS 1.1"
  type        = "SERVICE_CONTROL_POLICY"

  content = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "DenyRootAccountAccess"
        Effect = "Deny"
        Action = "*"
        Resource = "*"
        Condition = {
          StringLike = {
            "aws:PrincipalArn" = ["arn:aws:iam::*:root"]
          }
        }
      }
    ]
  })
}

resource "aws_organizations_policy_attachment" "deny_root_prod" {
  policy_id = aws_organizations_policy.deny_root_actions.id
  target_id = var.prod_ou_id
}
```

---

## SCP Library

### 1. Region Restriction

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyNonApprovedRegions",
      "Effect": "Deny",
      "NotAction": [
        "iam:*", "organizations:*", "support:*", "sts:*",
        "cloudfront:*", "route53:*", "waf:*", "budgets:*",
        "globalaccelerator:*", "health:*", "s3:GetBucketLocation",
        "trustedadvisor:*", "account:*"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "aws:RequestedRegion": ["us-east-1", "us-west-2", "eu-west-1"]
        },
        "StringNotLike": {
          "aws:PrincipalARN": [
            "arn:aws:iam::*:role/BreakGlassRole",
            "arn:aws:iam::*:role/TerraformRole"
          ]
        }
      }
    }
  ]
}
```

### 2. Protect Security Tooling

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyDisableGuardDuty",
      "Effect": "Deny",
      "Action": [
        "guardduty:DeleteDetector",
        "guardduty:DisassociateFromMasterAccount",
        "guardduty:DisassociateMembers",
        "guardduty:StopMonitoringMembers",
        "guardduty:UpdateDetector"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotLike": {
          "aws:PrincipalARN": "arn:aws:iam::*:role/SecurityAdminRole"
        }
      }
    },
    {
      "Sid": "DenyDisableSecurityHub",
      "Effect": "Deny",
      "Action": [
        "securityhub:DisableSecurityHub",
        "securityhub:DeleteInvitations",
        "securityhub:DisassociateFromMasterAccount"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotLike": {
          "aws:PrincipalARN": "arn:aws:iam::*:role/SecurityAdminRole"
        }
      }
    },
    {
      "Sid": "DenyStopCloudTrail",
      "Effect": "Deny",
      "Action": [
        "cloudtrail:StopLogging",
        "cloudtrail:DeleteTrail",
        "cloudtrail:UpdateTrail",
        "cloudtrail:PutEventSelectors"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotLike": {
          "aws:PrincipalARN": "arn:aws:iam::*:role/SecurityAdminRole"
        }
      }
    }
  ]
}
```

### 3. Enforce Encryption at Rest

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyUnencryptedS3PutObject",
      "Effect": "Deny",
      "Action": "s3:PutObject",
      "Resource": "*",
      "Condition": {
        "StringNotEquals": {
          "s3:x-amz-server-side-encryption": ["aws:kms", "AES256"]
        },
        "Null": {
          "s3:x-amz-server-side-encryption": "true"
        }
      }
    },
    {
      "Sid": "DenyUnencryptedRDSCreation",
      "Effect": "Deny",
      "Action": ["rds:CreateDBInstance", "rds:RestoreDBInstanceFromDBSnapshot"],
      "Resource": "*",
      "Condition": {
        "Bool": {
          "rds:StorageEncrypted": "false"
        }
      }
    },
    {
      "Sid": "DenyUnencryptedEBSVolume",
      "Effect": "Deny",
      "Action": "ec2:CreateVolume",
      "Resource": "*",
      "Condition": {
        "Bool": {
          "ec2:Encrypted": "false"
        }
      }
    }
  ]
}
```

### 4. Prevent Privilege Escalation

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyIAMPrivilegeEscalation",
      "Effect": "Deny",
      "Action": [
        "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion",
        "iam:PassRole",
        "iam:AttachUserPolicy",
        "iam:AttachGroupPolicy",
        "iam:PutUserPolicy",
        "iam:PutGroupPolicy",
        "iam:AddUserToGroup",
        "iam:CreateAccessKey",
        "iam:CreateLoginProfile",
        "iam:UpdateLoginProfile",
        "iam:UpdateAssumeRolePolicy"
      ],
      "Resource": "*",
      "Condition": {
        "StringNotLike": {
          "aws:PrincipalARN": [
            "arn:aws:iam::*:role/TerraformRole",
            "arn:aws:iam::*:role/BreakGlassRole",
            "arn:aws:iam::*:role/IAMAdminRole"
          ]
        }
      }
    }
  ]
}
```

### 5. Deny All for Suspended Accounts

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "DenyAllAccess",
      "Effect": "Deny",
      "Action": "*",
      "Resource": "*",
      "Condition": {
        "StringNotLike": {
          "aws:PrincipalARN": "arn:aws:iam::*:role/BreakGlassRole"
        }
      }
    }
  ]
}
```

### 6. Require MFA for Sensitive Actions

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RequireMFAForSensitiveActions",
      "Effect": "Deny",
      "Action": [
        "iam:DeleteVirtualMFADevice",
        "iam:DeactivateMFADevice",
        "organizations:LeaveOrganization"
      ],
      "Resource": "*",
      "Condition": {
        "BoolIfExists": {
          "aws:MultiFactorAuthPresent": "false"
        }
      }
    }
  ]
}
```

---

## SCP Rollout Procedure

```bash
# Step 1: Validate policy syntax
aws organizations validate-policy \
  --policy-text file://new-scp.json \
  --policy-type SERVICE_CONTROL_POLICY

# Step 2: Apply to sandbox OU only
aws organizations attach-policy \
  --policy-id p-xxxxxxxxxx \
  --target-id ou-sandbox-xxxxxxxxxx

# Step 3: Monitor CloudTrail for unexpected denies (24-72 hours)
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=RestrictedByOrganizationsPolicy \
  --max-results 50

# Step 4: If no issues, apply to staging OU
aws organizations attach-policy \
  --policy-id p-xxxxxxxxxx \
  --target-id ou-staging-xxxxxxxxxx

# Step 5: Apply to production OU after staging validation
aws organizations attach-policy \
  --policy-id p-xxxxxxxxxx \
  --target-id ou-prod-xxxxxxxxxx
```

---

## Debugging SCP Denies

```bash
# Simulate policy evaluation (Policy Simulator)
aws iam simulate-principal-policy \
  --policy-source-arn arn:aws:iam::123456789012:role/DeveloperRole \
  --action-names ec2:TerminateInstances \
  --resource-arns "arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef0"

# Check which SCPs apply to an account
aws organizations list-policies-for-target \
  --target-id <account-id> \
  --filter SERVICE_CONTROL_POLICY

# Check policy content
aws organizations describe-policy \
  --policy-id <policy-id> \
  --query 'Policy.Content' --output text | jq .

# CloudTrail — find AccessDenied from SCP
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=CreateVolume \
  --max-results 20 | \
  jq '.Events[] | select(.CloudTrailEvent | fromjson | .errorCode == "AccessDenied")'
```

---

## Cost Implications

SCPs are completely free. The only cost is the operational overhead of managing them and the CloudTrail logging that helps debug SCP denies (standard CloudTrail rates).

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| No break-glass exemption in Deny SCPs | Always add `StringNotLike aws:PrincipalARN BreakGlassRole` |
| Attaching SCP to root without testing | Test in sandbox OU for 48+ hours first |
| Using Allow SCPs (not just Deny) | Understand Allow SCPs only set max boundary; prefer using Deny SCPs |
| Denying global services in region restriction | Exclude IAM, S3, Route53, CloudFront from region restriction |
| No documentation on SCP purpose | Add `description` field with compliance control reference |
| Testing SCP with admin account | Management account SCPs don't apply to management account by default |
| Not monitoring for unexpected denies | Set up CloudTrail alarm for AccessDenied from SCPs |

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
