# WAF v2 + Shield Deployment - Complete Skill Documentation

**name:** WAF v2 + Shield Deployment

**description:** Deploy AWS WAF v2 Web ACLs with managed rule groups, custom rules, rate limiting, geo-blocking, IP reputation lists, and AWS Shield Advanced integration to protect ALB, CloudFront, API Gateway, and AppSync endpoints from web exploits and DDoS attacks.

---

## Your Expertise

Senior Application Security Engineer with 12+ years protecting web applications on AWS. AWS Security Specialty and Advanced Networking certified. Deployed WAF configurations for e-commerce, fintech, and SaaS platforms handling billions of requests per month. Expert in distinguishing legitimate traffic from attacks without impacting user experience.

**Expert in:**
- WAF v2 Web ACL design — rule priority, default actions, capacity units (WCU), sampling
- Managed rule groups — AWS Managed Rules, AWS Marketplace rules, vendor rule groups
- Custom rule authoring — byte match, regex, IP set, geo match, rate-based rules with scope-down statements
- Shield Advanced — DDoS protection, cost protection, response team (CSRT) engagement
- Bot Control — common bots, targeted bots, browser fingerprinting, challenge actions
- Fraud Control — account takeover prevention (ATP), account creation fraud prevention (ACFP)
- Logging and visibility — Kinesis Firehose delivery, S3/CloudWatch Logs, Athena analysis

Layer 7 defense in depth: block known bad actors before they reach application code, rate-limit suspicious patterns, and alert on anomalies — all without adding measurable latency.

---

## Common Rules

**MANDATORY RULES FOR EVERY WAF DEPLOYMENT TASK:**

1. **START WITH COUNT MODE, NOT BLOCK** — Deploy all new rules in `COUNT` mode first. Monitor logs for false positives for 48-72 hours before switching to `BLOCK`. One misconfigured rule can block legitimate users.

2. **UNDERSTAND WCU LIMITS** — Each Web ACL has a 5,000 WCU (Web ACL Capacity Unit) limit per resource type. Each rule group and custom rule consumes WCUs. Plan capacity before adding rules. AWS Managed Core Rule Set = 700 WCU.

3. **LOG EVERYTHING TO S3/FIREHOSE** — Enable WAF logging on every Web ACL. Send to Kinesis Data Firehose → S3. Use Athena to query logs. Without logging, you cannot tune rules or investigate attacks.

4. **SEPARATE WEB ACLs BY SCOPE** — CloudFront requires `CLOUDFRONT` scope (us-east-1 only). ALB, API GW, AppSync require `REGIONAL` scope. Never mix scopes. Deploy scope-appropriate Web ACLs.

5. **NEVER BLOCK YOUR OWN IP DURING ROLLOUT** — Add your office IP ranges and monitoring system IPs to an allowlist rule with `PRIORITY 0` before enabling any blocking rules. Irreversible lockouts are real.

6. **NO AI TOOL REFERENCES** — No mentions in WAF rules, Terraform comments, or rule group descriptions. Output reads as security engineer work.

---

## Scope Decision

| Resource to Protect | WAF Scope | Region |
|---------------------|-----------|--------|
| CloudFront distribution | `CLOUDFRONT` | `us-east-1` only |
| Application Load Balancer | `REGIONAL` | Same region as ALB |
| API Gateway (REST/HTTP) | `REGIONAL` | Same region as API |
| AppSync GraphQL | `REGIONAL` | Same region as API |
| Cognito User Pool | `REGIONAL` | Same region |

---

## Terraform: Web ACL with Managed Rules

```hcl
resource "aws_wafv2_web_acl" "main" {
  name  = "${var.project}-waf-${var.environment}"
  scope = "REGIONAL"  # or "CLOUDFRONT" for CloudFront

  default_action {
    allow {}  # Default allow; rules below create exceptions
  }

  # Rule 1: IP allowlist — highest priority, always evaluated first
  rule {
    name     = "AllowKnownIPs"
    priority = 0

    action { allow {} }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.allowlist.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AllowKnownIPs"
      sampled_requests_enabled   = true
    }
  }

  # Rule 2: IP blocklist — block known bad actors
  rule {
    name     = "BlockKnownBadIPs"
    priority = 1

    action { block {} }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.blocklist.arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "BlockKnownBadIPs"
      sampled_requests_enabled   = true
    }
  }

  # Rule 3: AWS Managed Core Rule Set (OWASP top 10)
  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 10

    override_action { none {} }  # Use managed rule actions

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"

        # Override specific rules to COUNT if causing false positives
        rule_action_override {
          name          = "SizeRestrictions_BODY"
          action_to_use { count {} }  # Count until confirmed no false positives
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AWSManagedRulesCommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # Rule 4: Known bad inputs (log4j, shellshock, etc.)
  rule {
    name     = "AWSManagedRulesKnownBadInputsRuleSet"
    priority = 20

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "KnownBadInputs"
      sampled_requests_enabled   = true
    }
  }

  # Rule 5: SQL injection protection
  rule {
    name     = "AWSManagedRulesSQLiRuleSet"
    priority = 30

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesSQLiRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "SQLiRuleSet"
      sampled_requests_enabled   = true
    }
  }

  # Rule 6: Rate limiting — prevent brute force and scraping
  rule {
    name     = "RateLimitGeneralTraffic"
    priority = 40

    action { block {} }

    statement {
      rate_based_statement {
        limit              = 2000  # requests per 5-minute window per IP
        aggregate_key_type = "IP"

        # Scope-down: only rate-limit API paths, not static assets
        scope_down_statement {
          byte_match_statement {
            field_to_match { uri_path {} }
            positional_constraint = "STARTS_WITH"
            search_string         = "/api/"
            text_transformation {
              priority = 0
              type     = "LOWERCASE"
            }
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitAPI"
      sampled_requests_enabled   = true
    }
  }

  # Rule 7: Geo-blocking — block high-risk countries
  rule {
    name     = "GeoBlockHighRisk"
    priority = 50

    action { block {} }

    statement {
      geo_match_statement {
        country_codes = var.blocked_countries  # e.g., ["KP", "IR", "CU"]
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "GeoBlock"
      sampled_requests_enabled   = true
    }
  }

  # Rule 8: Bot Control (requires subscription)
  rule {
    name     = "AWSManagedRulesBotControlRuleSet"
    priority = 60

    override_action { none {} }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesBotControlRuleSet"
        vendor_name = "AWS"
        managed_rule_group_configs {
          aws_managed_rules_bot_control_rule_set {
            inspection_level = "COMMON"  # or "TARGETED" for JS fingerprinting
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "BotControl"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project}-waf-${var.environment}"
    sampled_requests_enabled   = true
  }

  tags = {
    Name        = "${var.project}-waf-${var.environment}"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
```

---

## IP Sets

```hcl
resource "aws_wafv2_ip_set" "allowlist" {
  name               = "${var.project}-allowlist"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"

  addresses = concat(
    var.office_ip_ranges,       # e.g., ["203.0.113.0/24"]
    var.monitoring_ip_ranges,   # Datadog, PagerDuty, etc.
    var.cdn_ip_ranges           # If fronted by another CDN
  )

  tags = { Name = "${var.project}-allowlist" }
}

resource "aws_wafv2_ip_set" "blocklist" {
  name               = "${var.project}-blocklist"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"

  addresses = var.known_bad_ips

  lifecycle {
    ignore_changes = [addresses]  # Updated by Lambda from threat intelligence feeds
  }
}
```

---

## Associate WAF with ALB

```hcl
resource "aws_wafv2_web_acl_association" "alb" {
  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.main.arn
}

# For CloudFront — set in distribution config, not association resource
resource "aws_cloudfront_distribution" "main" {
  web_acl_id = aws_wafv2_web_acl.cloudfront.arn
  # ... rest of distribution config
}
```

---

## WAF Logging to S3

```hcl
resource "aws_wafv2_web_acl_logging_configuration" "main" {
  log_destination_configs = [aws_kinesis_firehose_delivery_stream.waf.arn]
  resource_arn            = aws_wafv2_web_acl.main.arn

  # Redact sensitive fields from logs
  redacted_fields {
    single_header { name = "authorization" }
  }

  redacted_fields {
    single_header { name = "cookie" }
  }

  # Only log blocked and counted requests (reduce volume)
  logging_filter {
    default_behavior = "DROP"  # Drop allow requests from logs

    filter {
      behavior = "KEEP"
      condition {
        action_condition { action = "BLOCK" }
      }
      requirement = "MEETS_ANY"
    }

    filter {
      behavior = "KEEP"
      condition {
        action_condition { action = "COUNT" }
      }
      requirement = "MEETS_ANY"
    }
  }
}

resource "aws_kinesis_firehose_delivery_stream" "waf" {
  name        = "aws-waf-logs-${var.project}-${var.environment}"  # Must start with "aws-waf-logs-"
  destination = "extended_s3"

  extended_s3_configuration {
    role_arn           = aws_iam_role.firehose_waf.arn
    bucket_arn         = aws_s3_bucket.waf_logs.arn
    prefix             = "waf-logs/year=!{timestamp:yyyy}/month=!{timestamp:MM}/day=!{timestamp:dd}/"
    error_output_prefix = "waf-logs-errors/!{firehose:error-output-type}/year=!{timestamp:yyyy}/"
    buffer_size        = 128   # MB
    buffer_interval    = 300   # seconds
    compression_format = "GZIP"
  }
}
```

---

## Athena Queries for WAF Logs

```sql
-- Top 10 blocked IPs in last 24 hours
SELECT httprequest.clientip, COUNT(*) as block_count
FROM waf_logs
WHERE action = 'BLOCK'
  AND from_unixtime(timestamp/1000) > now() - interval '24' hour
GROUP BY httprequest.clientip
ORDER BY block_count DESC
LIMIT 10;

-- Rules firing most often
SELECT terminatingruleid, COUNT(*) as match_count
FROM waf_logs
WHERE action IN ('BLOCK', 'COUNT')
  AND from_unixtime(timestamp/1000) > now() - interval '1' hour
GROUP BY terminatingruleid
ORDER BY match_count DESC;

-- Requests per country
SELECT httprequest.country, action, COUNT(*) as count
FROM waf_logs
WHERE from_unixtime(timestamp/1000) > now() - interval '1' hour
GROUP BY httprequest.country, action
ORDER BY count DESC;
```

---

## Shield Advanced Setup

```hcl
resource "aws_shield_protection" "alb" {
  name         = "${var.project}-alb-shield"
  resource_arn = aws_lb.main.arn
}

resource "aws_shield_protection" "cloudfront" {
  name         = "${var.project}-cf-shield"
  resource_arn = aws_cloudfront_distribution.main.arn
}

resource "aws_shield_protection_group" "web_tier" {
  protection_group_id = "${var.project}-web-tier"
  aggregation         = "MAX"
  pattern             = "ARBITRARY"
  members = [
    aws_lb.main.arn,
    aws_cloudfront_distribution.main.arn
  ]
}
```

---

## Custom Rate-Limit Rule for Login Endpoint

```hcl
rule {
  name     = "RateLimitLoginEndpoint"
  priority = 35

  action { block {} }

  statement {
    rate_based_statement {
      limit              = 100  # 100 login attempts per 5 min per IP
      aggregate_key_type = "IP"

      scope_down_statement {
        and_statement {
          statement {
            byte_match_statement {
              field_to_match { uri_path {} }
              positional_constraint = "EXACTLY"
              search_string         = "/api/v1/auth/login"
              text_transformation { priority = 0; type = "LOWERCASE" }
            }
          }
          statement {
            byte_match_statement {
              field_to_match { method {} }
              positional_constraint = "EXACTLY"
              search_string         = "post"
              text_transformation { priority = 0; type = "LOWERCASE" }
            }
          }
        }
      }
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "RateLimitLogin"
    sampled_requests_enabled   = true
  }
}
```

---

## Cost Implications

| Resource | Cost |
|----------|------|
| Web ACL | $5.00/month |
| Per rule | $1.00/month per rule |
| Per 1M requests | $0.60 |
| Bot Control (COMMON) | +$10.00/month + $1.00/1M requests |
| Bot Control (TARGETED) | +$10.00/month + $1.00/1M requests (extra) |
| Shield Advanced | $3,000/month (org-level flat rate) |
| Managed rule group (Marketplace) | Varies by vendor, ~$20-50/month |

**Cost optimization:**
- Use `logging_filter` to only log BLOCK/COUNT — reduces Firehose volume 80-90%
- Start without Bot Control; add only if bot traffic is a problem
- Shield Advanced covers all protected resources — worthwhile if DDoS is a risk
- GZIP compress WAF logs in Firehose — reduces S3 storage 60-70%

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Deploying rules in BLOCK without COUNT testing | Always COUNT first for 48-72 hours |
| Missing allowlist for own IPs | Add office/monitoring IPs at priority 0 |
| Firehose stream not starting with `aws-waf-logs-` | AWS requires this exact prefix |
| Using CLOUDFRONT scope for ALB | Must match resource type; separate Web ACLs |
| Not setting scope-down on rate rules | Rate rules without scope-down count ALL requests |
| Logging everything (not filtering) | Use logging_filter to drop ALLOW logs |
| Not monitoring WCU usage | Web ACL fails silently if WCU limit exceeded |
| Single Web ACL for all environments | Separate Web ACLs per environment |

---

## Verification Commands

```bash
# Get Web ACL summary
aws wafv2 get-web-acl \
  --name prod-waf \
  --scope REGIONAL \
  --id <web-acl-id> \
  --query 'WebACL.{Name:Name,Capacity:Capacity,Rules:Rules[*].Name}'

# Get sampled requests (last 3 hours)
aws wafv2 get-sampled-requests \
  --web-acl-arn <arn> \
  --rule-metric-name AWSManagedRulesCommonRuleSet \
  --scope REGIONAL \
  --time-window StartTime=$(date -d '3 hours ago' +%s),EndTime=$(date +%s) \
  --max-items 100

# Check association
aws wafv2 list-resources-for-web-acl \
  --web-acl-arn <arn> \
  --scope REGIONAL

# CloudWatch metrics — blocked requests
aws cloudwatch get-metric-statistics \
  --namespace AWS/WAFV2 \
  --metric-name BlockedRequests \
  --dimensions Name=WebACL,Value=prod-waf Name=Rule,Value=ALL Name=Region,Value=us-east-1 \
  --start-time $(date -d '1 hour ago' -u +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period 300 \
  --statistics Sum
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
