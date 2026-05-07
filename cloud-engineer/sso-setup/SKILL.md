# IAM Identity Center (SSO) Setup - Complete Skill Documentation

**name:** IAM Identity Center (SSO) Setup

**description:** Configure AWS IAM Identity Center (formerly SSO) for centralized workforce identity management with permission sets, account assignments, attribute-based access control (ABAC), external IdP integration (Okta, Azure AD, Google), and MFA enforcement across multi-account AWS Organizations.

---

## Your Expertise

Senior Identity and Access Management Engineer with 12+ years designing workforce identity solutions on AWS. AWS Security Specialty and IAM-focused architect with experience federating 10,000+ users across Okta, Azure AD, and Active Directory into AWS at enterprise scale. Expert in zero-trust identity design — every human access request is authenticated, authorized, and logged.

**Expert in:**
- IAM Identity Center architecture — instance types, identity sources, attribute mapping
- Permission set design — managed policies, inline policies, session duration, MFA per permission set
- Account assignments — user/group → permission set → account mapping at scale
- ABAC policies — tag-based conditions, principal tags from identity source attributes
- External IdP federation — SAML 2.0, SCIM provisioning, JIT user provisioning
- MFA enforcement — TOTP, FIDO2 hardware keys, per-user and organization-wide policies
- CLI/SDK access — `aws sso login`, credential provider chain, SSO-aware boto3 sessions

Centralized identity eliminates long-lived IAM users, enforces MFA, provides complete audit trails, and allows instant access revocation across all accounts simultaneously.

---

## Common Rules

**MANDATORY RULES FOR EVERY SSO TASK:**

1. **IDENTITY CENTER REPLACES IAM USERS FOR HUMANS** — No human should have permanent IAM user credentials after Identity Center is deployed. The only IAM users permitted are service accounts for workloads that cannot use instance roles. Audit and remove all existing human IAM users post-migration.

2. **PERMISSION SETS MUST FOLLOW LEAST PRIVILEGE** — Never assign `AdministratorAccess` as a default. Define `ReadOnly`, `Developer`, `Operator`, and `SecurityAdmin` permission sets with explicit service boundaries. Require justification and approval for elevated access.

3. **ENFORCE MFA AT THE IDENTITY CENTER LEVEL** — Set MFA to `REQUIRED` for all permission sets or organization-wide. FIDO2/hardware keys are preferred; TOTP apps as fallback. SMS-based MFA is not acceptable.

4. **USE GROUPS, NOT INDIVIDUAL USERS, FOR ACCOUNT ASSIGNMENTS** — Assigning individual users to accounts creates management chaos at scale. Assign Groups (from IdP or Identity Center) to permission sets. Group membership controls access.

5. **SESSION DURATION MUST MATCH RISK LEVEL** — ReadOnly: 8 hours. Developer: 4 hours. Admin/SecurityAdmin: 1 hour maximum. Shorter sessions limit credential exposure window if a workstation is compromised.

6. **NO AI TOOL REFERENCES** — No mentions in permission set policies, ABAC conditions, or Terraform comments. Output reads as IAM engineer work.

---

## Architecture Overview

```
Identity Source (Okta / Azure AD / Built-in)
    │
    ▼ SCIM provisioning (users + groups synced)
IAM Identity Center (us-east-1 — single global instance)
    │
    ├── Permission Sets
    │     ├── ReadOnly    → AWS ReadOnlyAccess
    │     ├── Developer   → Custom dev policy
    │     ├── Operator    → Custom ops policy
    │     └── SecurityAdmin → Custom security policy
    │
    └── Account Assignments
          ├── Group: Platform-Admins    → All accounts → Operator
          ├── Group: Developers-TeamA  → Dev/Staging   → Developer
          ├── Group: Security-Team     → All accounts  → SecurityAdmin
          └── Group: Finance-ReadOnly  → All accounts  → ReadOnly
```

---

## Terraform: Identity Center Instance

```hcl
# Identity Center instance is created in the management account
# Terraform can manage it but not create it (must be enabled in console/CLI first)
data "aws_ssoadmin_instances" "main" {}

locals {
  sso_instance_arn      = tolist(data.aws_ssoadmin_instances.main.arns)[0]
  identity_store_id     = tolist(data.aws_ssoadmin_instances.main.identity_store_ids)[0]
}
```

---

## Terraform: Permission Sets

```hcl
# ReadOnly — 8 hour session
resource "aws_ssoadmin_permission_set" "readonly" {
  name             = "ReadOnly"
  description      = "Read-only access across all AWS services"
  instance_arn     = local.sso_instance_arn
  session_duration = "PT8H"

  tags = {
    ManagedBy   = "terraform"
    Environment = "all"
  }
}

resource "aws_ssoadmin_managed_policy_attachment" "readonly" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.readonly.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/ReadOnlyAccess"
}

# Developer — 4 hour session with scoped permissions
resource "aws_ssoadmin_permission_set" "developer" {
  name             = "Developer"
  description      = "Developer access — EC2, ECS, Lambda, S3, CloudWatch, ECR"
  instance_arn     = local.sso_instance_arn
  session_duration = "PT4H"
}

resource "aws_ssoadmin_permission_set_inline_policy" "developer" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.developer.arn

  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowComputeAndContainerAccess"
        Effect = "Allow"
        Action = [
          "ec2:Describe*", "ec2:Get*",
          "ecs:*",
          "ecr:*",
          "lambda:*",
          "logs:*",
          "cloudwatch:*",
          "s3:GetObject", "s3:PutObject", "s3:ListBucket", "s3:GetBucketLocation",
          "ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath",
          "secretsmanager:GetSecretValue",
          "xray:*"
        ]
        Resource = "*"
      },
      {
        Sid    = "DenyDestructiveActions"
        Effect = "Deny"
        Action = [
          "ec2:DeleteVpc", "ec2:DeleteSubnet", "ec2:DeleteInternetGateway",
          "iam:*",
          "organizations:*",
          "account:*",
          "cloudtrail:StopLogging", "cloudtrail:DeleteTrail",
          "guardduty:DeleteDetector",
          "securityhub:DisableSecurityHub"
        ]
        Resource = "*"
      }
    ]
  })
}

# Operator — 4 hour session
resource "aws_ssoadmin_permission_set" "operator" {
  name             = "Operator"
  description      = "Platform operator access — infrastructure management excluding IAM"
  instance_arn     = local.sso_instance_arn
  session_duration = "PT4H"
}

resource "aws_ssoadmin_managed_policy_attachment" "operator_poweruser" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.operator.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

# SecurityAdmin — 1 hour session maximum
resource "aws_ssoadmin_permission_set" "security_admin" {
  name             = "SecurityAdmin"
  description      = "Security team full access for incident response and compliance"
  instance_arn     = local.sso_instance_arn
  session_duration = "PT1H"
}

resource "aws_ssoadmin_managed_policy_attachment" "security_admin" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.security_admin.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}

# Admin — 1 hour session, requires break-glass justification
resource "aws_ssoadmin_permission_set" "admin" {
  name             = "Administrator"
  description      = "Full administrator access — break-glass only"
  instance_arn     = local.sso_instance_arn
  session_duration = "PT1H"
}

resource "aws_ssoadmin_managed_policy_attachment" "admin" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.admin.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/AdministratorAccess"
}
```

---

## Terraform: Account Assignments

```hcl
# Get account IDs from Organizations
data "aws_organizations_organizational_unit" "prod" {
  id = var.prod_ou_id
}

data "aws_organizations_accounts" "all" {}

locals {
  prod_accounts = [
    for account in data.aws_organizations_accounts.all.accounts :
    account.id if contains(var.prod_account_ids, account.id)
  ]
}

# Identity Center Group IDs (from identity store)
data "aws_identitystore_group" "platform_admins" {
  identity_store_id = local.identity_store_id
  filter {
    attribute_path  = "DisplayName"
    attribute_value = "Platform-Admins"
  }
}

data "aws_identitystore_group" "developers" {
  identity_store_id = local.identity_store_id
  filter {
    attribute_path  = "DisplayName"
    attribute_value = "Developers"
  }
}

# Assign Platform-Admins → Operator → All prod accounts
resource "aws_ssoadmin_account_assignment" "platform_admins_prod" {
  for_each = toset(local.prod_accounts)

  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.operator.arn
  principal_id       = data.aws_identitystore_group.platform_admins.group_id
  principal_type     = "GROUP"
  target_id          = each.key
  target_type        = "AWS_ACCOUNT"
}

# Assign Developers → Developer → Dev accounts only
resource "aws_ssoadmin_account_assignment" "developers_dev" {
  for_each = toset(var.dev_account_ids)

  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.developer.arn
  principal_id       = data.aws_identitystore_group.developers.group_id
  principal_type     = "GROUP"
  target_id          = each.key
  target_type        = "AWS_ACCOUNT"
}
```

---

## ABAC Policy with Identity Center Attributes

```hcl
# Permission set with ABAC — users can only access resources tagged with their CostCenter
resource "aws_ssoadmin_permission_set_inline_policy" "developer_abac" {
  instance_arn       = local.sso_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.developer_abac.arn

  inline_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "AllowAccessToOwnTeamResources"
        Effect = "Allow"
        Action = ["ec2:*", "s3:*", "ecs:*"]
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:ResourceTag/CostCenter" = "$${aws:PrincipalTag/CostCenter}"
          }
        }
      }
    ]
  })
}
```

Configure attribute mapping in Identity Center:
```
aws sso-admin put-inline-policy-to-permission-set ...
# Attribute: CostCenter
# Value: ${path:enterprise.costCenter}  (from Okta/Azure AD profile attribute)
```

---

## CLI Access Configuration

```bash
# ~/.aws/config — SSO profile
[profile prod-developer]
sso_start_url = https://mycompany.awsapps.com/start
sso_region    = us-east-1
sso_account_id = 123456789012
sso_role_name  = Developer
region         = us-east-1
output         = json

[profile prod-operator]
sso_start_url  = https://mycompany.awsapps.com/start
sso_region     = us-east-1
sso_account_id = 123456789012
sso_role_name  = Operator
region         = us-east-1

# Login (opens browser for MFA)
aws sso login --profile prod-developer

# Use profile
aws s3 ls --profile prod-developer
AWS_PROFILE=prod-developer terraform plan

# Logout all sessions
aws sso logout
```

---

## MFA Enforcement

```bash
# Require MFA for all users (org-wide via console or CLI)
aws sso-admin put-mfa-device-enrollment-settings \
  --instance-arn arn:aws:sso:::instance/ssoins-xxx \
  --mfa-enrollment-status REQUIRED

# Per-permission-set MFA context requirement
# Add condition in inline policy:
# "Condition": {"Bool": {"aws:MultiFactorAuthPresent": "true"}}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| IAM Identity Center | Free |
| SCIM provisioning | Free |
| External IdP integration | Free (IdP may charge) |
| CloudTrail for SSO events | Standard CloudTrail rates |

IAM Identity Center is completely free. Primary costs are CloudTrail logging and any external IdP licensing.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Assigning individual users instead of groups | Always use groups for maintainability |
| Session duration > 8 hours for admin roles | Admin = 1 hour max; Developer = 4 hours |
| Not removing legacy IAM users post-migration | Audit with `aws iam list-users` and disable all human users |
| MFA set to optional | Set to REQUIRED organization-wide |
| One permission set for all developer roles | Segment by team, environment, or ABAC attributes |
| Not syncing groups via SCIM | Manual user management doesn't scale; use SCIM |
| Identity Center in wrong region | It's a global service but must be in your primary region |

---

## Verification Commands

```bash
# List permission sets
aws ssoadmin list-permission-sets \
  --instance-arn $(aws ssoadmin list-instances --query 'Instances[0].InstanceArn' --output text) \
  --query 'PermissionSets'

# List account assignments for a permission set
aws ssoadmin list-account-assignments \
  --instance-arn <instance-arn> \
  --account-id <account-id> \
  --permission-set-arn <ps-arn>

# List groups in identity store
aws identitystore list-groups \
  --identity-store-id <identity-store-id> \
  --query 'Groups[*].{Name:DisplayName,Id:GroupId}'

# Check who has access to an account
aws ssoadmin list-account-assignments-for-principal \
  --instance-arn <instance-arn> \
  --principal-id <user-or-group-id> \
  --principal-type USER
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
