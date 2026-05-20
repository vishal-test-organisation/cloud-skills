terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = "us-east-1"
}

# ─── RDS (PostgreSQL) ─────────────────────────────────────────────────────────
resource "aws_db_instance" "app_db" {
  identifier        = "cloudskills-prod"
  engine            = "postgres"
  engine_version    = "14.10"
  instance_class    = "db.t3.medium"
  allocated_storage = 100
  db_name           = "cloudskills"
  username          = "admin"
  password          = var.db_password

  # SOC2 C1.2 gap: encryption not enabled
  storage_encrypted = false

  # SOC2 A1.2 gap: single-AZ, no multi-AZ failover
  multi_az = false

  # Backups only 3 days — below SOC2 30-day recommendation
  backup_retention_period = 3
  backup_window           = "03:00-04:00"

  # Publicly accessible — SOC2 CC6.6 critical finding
  publicly_accessible = true

  skip_final_snapshot = true
}

# ─── S3 Bucket ────────────────────────────────────────────────────────────────
resource "aws_s3_bucket" "user_uploads" {
  bucket = "cloudskills-user-uploads"
}

# SOC2 C1.2 gap: no encryption on S3 bucket
# resource "aws_s3_bucket_server_side_encryption_configuration" not configured

# SOC2 CC6.6 critical finding: public ACL allowed
resource "aws_s3_bucket_acl" "user_uploads_acl" {
  bucket = aws_s3_bucket.user_uploads.id
  acl    = "public-read"  # Any file uploaded is publicly readable
}

# No bucket versioning — no audit trail for file changes
# No lifecycle rules — objects accumulate forever (GDPR retention gap)

# ─── Security Groups ──────────────────────────────────────────────────────────
resource "aws_security_group" "app_sg" {
  name        = "cloudskills-app"
  description = "App security group"
  vpc_id      = var.vpc_id

  # SOC2 CC6.6 critical finding: SSH open to the world
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SOC2 CC6.6: database port open to all
  ingress {
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ─── CloudTrail ───────────────────────────────────────────────────────────────
# SOC2 CC4.1 gap: CloudTrail is NOT configured
# No API call logging, no config change tracking

# ─── IAM ─────────────────────────────────────────────────────────────────────
resource "aws_iam_user" "deploy_user" {
  name = "cloudskills-deploy"
}

# SOC2 CC6.3 gap: wildcard permissions — not least-privilege
resource "aws_iam_user_policy" "deploy_policy" {
  name = "deploy-policy"
  user = aws_iam_user.deploy_user.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["*"]          # Full admin access — critical finding
      Resource = ["*"]
    }]
  })
}

variable "db_password" {}
variable "vpc_id" {}
