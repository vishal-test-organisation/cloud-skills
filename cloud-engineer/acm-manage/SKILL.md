# ACM Certificate Management - Complete Skill Documentation

**name:** ACM Certificate Management

**description:** Issue, validate, and manage AWS Certificate Manager (ACM) SSL/TLS certificates with DNS validation via Route53, automatic renewal, ALB and CloudFront attachment, wildcard certificates, private CA integration, and certificate expiry monitoring across multi-account environments.

---

## Your Expertise

Senior Infrastructure and Security Engineer with 12+ years managing PKI and TLS certificate infrastructure on AWS. AWS Solutions Architect Professional certified. Managed hundreds of ACM certificates across production workloads with zero expiry incidents, zero-downtime certificate rotations, and compliance-grade private CA hierarchies for internal mTLS.

**Expert in:**
- ACM public certificates — DNS and email validation, wildcard certs, multi-domain SANs
- DNS validation via Route53 — automated CNAME record creation, cross-account validation
- ALB HTTPS listeners — certificate attachment, Server Name Indication (SNI), multiple certs per listener
- CloudFront + ACM — us-east-1 requirement, custom SSL, minimum TLS protocol versions
- ACM Private CA — root/subordinate CA hierarchy, internal mTLS, certificate issuance automation
- Certificate expiry monitoring — EventBridge, CloudWatch alarms, automatic renewal verification
- Cross-account sharing — RAM sharing ACM Private CA across accounts, cross-account ALB certs

Every public endpoint encrypted with TLS 1.2 minimum, automated renewal before 60-day expiry window, and proactive monitoring so certificate expiry never causes production outages.

---

## Common Rules

**MANDATORY RULES FOR EVERY ACM TASK:**

1. **DNS VALIDATION OVER EMAIL VALIDATION** — DNS validation never expires (the CNAME record persists and renews automatically). Email validation requires manual action every 825 days. Always use DNS validation for all ACM certificates.

2. **ACM FOR CLOUDFRONT MUST BE IN US-EAST-1** — CloudFront is a global service but requires ACM certificates in the `us-east-1` region only. Certificate in any other region cannot be attached to CloudFront. Use a separate AWS provider block for us-east-1 in Terraform.

3. **WILDCARD CERTS COVER ONE LEVEL ONLY** — `*.example.com` covers `api.example.com` and `app.example.com` but NOT `api.staging.example.com`. For subdomains, issue separate certs or add explicit SANs.

4. **MONITOR FOR RENEWAL FAILURES** — ACM auto-renews certificates if DNS validation CNAME records are in place, but renewal can fail if Route53 hosted zone is deleted or CNAME is removed. Set up EventBridge rule on `ACM Certificate Approaching Expiry` events (60-day warning).

5. **PRIVATE CA FOR INTERNAL SERVICES** — Use ACM Private CA for service-to-service mTLS, internal APIs, and databases. Never use self-signed certificates in production — they are unmanageable at scale and audit bodies flag them.

6. **NO AI TOOL REFERENCES** — No mentions in certificate configurations, Terraform resources, or Lambda functions. Output reads as platform engineer work.

---

## Certificate Validation Methods

| Method | Auto-Renews | Requires | Use Case |
|--------|-------------|----------|----------|
| DNS (CNAME) | Yes (if CNAME stays) | Route53 or manual DNS entry | Preferred for all |
| Email | No (manual every 825d) | WHOIS email access | Domains not in Route53 |
| Private CA | Yes | ACM PCA | Internal mTLS |

---

## Terraform: Public Certificate with DNS Validation

```hcl
# Certificate in us-east-1 for CloudFront
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"
}

resource "aws_acm_certificate" "main" {
  provider          = aws.us_east_1  # CloudFront requires us-east-1
  domain_name       = var.domain_name            # e.g., "example.com"
  validation_method = "DNS"

  subject_alternative_names = [
    "*.${var.domain_name}",                       # Wildcard for all subdomains
    "www.${var.domain_name}",
  ]

  lifecycle {
    create_before_destroy = true  # Prevent downtime during cert replacement
  }

  tags = {
    Name        = var.domain_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Create DNS validation CNAME records in Route53
data "aws_route53_zone" "main" {
  name         = "${var.domain_name}."
  private_zone = false
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main.zone_id
}

# Wait for certificate to be issued
resource "aws_acm_certificate_validation" "main" {
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.cert_validation : record.fqdn]

  timeouts {
    create = "30m"
  }
}
```

---

## Terraform: Regional Certificate (for ALB)

```hcl
# Certificate in same region as ALB
resource "aws_acm_certificate" "alb" {
  domain_name       = var.domain_name
  validation_method = "DNS"

  subject_alternative_names = ["*.${var.domain_name}"]

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "alb_cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.alb.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      record = dvo.resource_record_value
      type   = dvo.resource_record_type
    }
  }

  allow_overwrite = true
  name            = each.value.name
  records         = [each.value.record]
  ttl             = 60
  type            = each.value.type
  zone_id         = data.aws_route53_zone.main.zone_id
}

resource "aws_acm_certificate_validation" "alb" {
  certificate_arn         = aws_acm_certificate.alb.arn
  validation_record_fqdns = [for record in aws_route53_record.alb_cert_validation : record.fqdn]
}
```

---

## Terraform: ALB HTTPS Listener with Certificate

```hcl
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = "443"
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"  # TLS 1.3 + 1.2, no 1.1/1.0
  certificate_arn   = aws_acm_certificate_validation.alb.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.main.arn
  }
}

# HTTP → HTTPS redirect
resource "aws_lb_listener" "http_redirect" {
  load_balancer_arn = aws_lb.main.arn
  port              = "80"
  protocol          = "HTTP"

  default_action {
    type = "redirect"
    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

# Additional certificate (SNI — multiple domains on same ALB)
resource "aws_lb_listener_certificate" "additional" {
  listener_arn    = aws_lb_listener.https.arn
  certificate_arn = aws_acm_certificate_validation.secondary.certificate_arn
}
```

---

## Terraform: CloudFront with ACM Certificate

```hcl
resource "aws_cloudfront_distribution" "main" {
  aliases = [var.domain_name, "www.${var.domain_name}"]

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.main.certificate_arn  # Must be us-east-1
    ssl_support_method       = "sni-only"   # sni-only (modern) vs vip ($600/month)
    minimum_protocol_version = "TLSv1.2_2021"  # Reject TLS 1.0/1.1
  }

  # ... origin, cache behaviors, etc.
}
```

---

## Certificate Expiry Monitoring

```hcl
# EventBridge rule for certificate approaching expiry
resource "aws_cloudwatch_event_rule" "cert_expiry" {
  name        = "acm-certificate-expiry-warning"
  description = "Alert when ACM certificate is within 60 days of expiry"

  event_pattern = jsonencode({
    source      = ["aws.acm"]
    detail-type = ["ACM Certificate Approaching Expiry"]
    detail = {
      DaysToExpiry = [{ numeric = ["<=", 60] }]
    }
  })
}

resource "aws_cloudwatch_event_target" "cert_expiry_sns" {
  rule      = aws_cloudwatch_event_rule.cert_expiry.name
  target_id = "CertExpiryAlert"
  arn       = aws_sns_topic.alerts.arn
}

# Also create a CloudWatch alarm for belt-and-suspenders
resource "aws_cloudwatch_metric_alarm" "cert_expiry" {
  alarm_name          = "acm-cert-days-to-expiry"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "DaysToExpiry"
  namespace           = "AWS/CertificateManager"
  period              = 86400  # Daily check
  statistic           = "Minimum"
  threshold           = 45
  alarm_actions       = [aws_sns_topic.alerts.arn]
  dimensions = {
    CertificateArn = aws_acm_certificate.main.arn
  }
}
```

---

## ACM Private CA

```hcl
# Root CA (store offline — this is just for subordinate CA issuance)
resource "aws_acmpca_certificate_authority" "root" {
  type = "ROOT"

  certificate_authority_configuration {
    key_algorithm     = "RSA_4096"
    signing_algorithm = "SHA512WITHRSA"

    subject {
      common_name         = "${var.org_name} Root CA"
      organization        = var.org_name
      organizational_unit = "Security"
      country             = "US"
    }
  }

  revocation_configuration {
    crl_configuration {
      enabled            = true
      expiration_in_days = 7
      s3_bucket_name     = aws_s3_bucket.crl.id
    }
  }

  permanent_deletion_time_in_days = 30
  tags = { Name = "${var.org_name}-root-ca" }
}

# Subordinate CA (operational — issues leaf certs)
resource "aws_acmpca_certificate_authority" "subordinate" {
  type = "SUBORDINATE"

  certificate_authority_configuration {
    key_algorithm     = "RSA_2048"
    signing_algorithm = "SHA256WITHRSA"

    subject {
      common_name         = "${var.org_name} Issuing CA"
      organization        = var.org_name
      organizational_unit = "Platform"
    }
  }
}
```

---

## ALB SSL Policy Selection

| Policy | TLS Versions | Use Case |
|--------|-------------|----------|
| ELBSecurityPolicy-TLS13-1-2-2021-06 | TLS 1.3, 1.2 | Recommended — modern browsers |
| ELBSecurityPolicy-TLS13-1-3-2021-06 | TLS 1.3 only | Strictest — may break older clients |
| ELBSecurityPolicy-2016-08 | TLS 1.0–1.3 | Legacy — avoid |

---

## Cost Implications

| Resource | Cost |
|----------|------|
| ACM Public Certificate | Free |
| ACM Private CA | $400/month per CA + $0.75/cert (first 1,000) |
| SNI-only CloudFront SSL | Free |
| Dedicated IP CloudFront SSL (vip) | $600/month |

**Note:** ACM public certificates are completely free. The $400/month Private CA cost only applies if you need internal mTLS with a private CA.

---

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| CloudFront cert not in us-east-1 | Use separate `aws.us_east_1` provider for CloudFront certs |
| Email validation (not DNS) | Switch to DNS validation — auto-renews without human action |
| Missing `create_before_destroy` lifecycle | Without it, Terraform destroys old cert before creating new = downtime |
| Not waiting for `aws_acm_certificate_validation` | ALB listener creation fails if cert not yet validated |
| Wildcard expecting `*.sub.example.com` coverage | Wildcard only covers one level — add explicit SANs for subdomains |
| No expiry monitoring | Set up EventBridge rule for `ACM Certificate Approaching Expiry` |
| TLS 1.0/1.1 in ALB SSL policy | Use `ELBSecurityPolicy-TLS13-1-2-2021-06` minimum |

---

## Verification Commands

```bash
# List all certificates and their status
aws acm list-certificates \
  --query 'CertificateSummaryList[*].{Domain:DomainName,ARN:CertificateArn,Status:Status}' \
  --output table

# Check certificate details and renewal status
aws acm describe-certificate \
  --certificate-arn <cert-arn> \
  --query 'Certificate.{Domain:DomainName,Status:Status,RenewalStatus:RenewalSummary.RenewalStatus,NotAfter:NotAfter}'

# Check which resources use a certificate
aws acm describe-certificate \
  --certificate-arn <cert-arn> \
  --query 'Certificate.InUseBy'

# Test TLS connection
openssl s_client -connect api.example.com:443 -servername api.example.com \
  | openssl x509 -noout -dates -subject -issuer

# Verify DNS validation records
dig CNAME _acme-challenge.example.com +short
```

---

**MIT License** — Free and open source. Heaptrace Technology Private Limited.
