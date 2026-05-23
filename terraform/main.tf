locals {
  app_name = "rita"
}

data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
}

# ── Networking: VPC & Subnet ──────────────────────────────────────────────────

resource "aws_vpc" "rita" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  tags = {
    Name = "${local.app_name}-vpc"
  }
}

resource "aws_internet_gateway" "rita" {
  vpc_id = aws_vpc.rita.id
  tags = {
    Name = "${local.app_name}-igw"
  }
}

resource "aws_subnet" "rita" {
  vpc_id                  = aws_vpc.rita.id
  cidr_block              = var.subnet_cidr
  map_public_ip_on_launch = true
  tags = {
    Name = "${local.app_name}-subnet-public"
  }
}

resource "aws_route_table" "rita" {
  vpc_id = aws_vpc.rita.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.rita.id
  }
}

resource "aws_route_table_association" "rita" {
  subnet_id      = aws_subnet.rita.id
  route_table_id = aws_route_table.rita.id
}

# ── Security Group ────────────────────────────────────────────────────────────

resource "aws_security_group" "rita" {
  name        = "${local.app_name}-sg"
  description = "Allow inbound API and SSH traffic"
  vpc_id      = aws_vpc.rita.id

  # HTTP / API Port
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # HTTPS
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH
  ingress {
    from_port   = 22
    to_port     = 22
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

# ── IAM Role — EC2 → CloudWatch Logs ─────────────────────────────────────────

resource "aws_iam_role" "rita_ec2" {
  name = "${local.app_name}-ec2-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "rita_cw_logs" {
  role       = aws_iam_role.rita_ec2.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

resource "aws_iam_instance_profile" "rita_ec2" {
  name = "${local.app_name}-ec2-profile"
  role = aws_iam_role.rita_ec2.name
}

# ── CloudWatch Log Group ──────────────────────────────────────────────────────

resource "aws_cloudwatch_log_group" "rita_app" {
  name              = "/rita/app"
  retention_in_days = var.log_retention_days
  tags              = { Name = "${local.app_name}-logs" }
}

# ── Alerting: SNS topic + email subscription ──────────────────────────────────

resource "aws_sns_topic" "rita_alerts" {
  name = "${local.app_name}-alerts"
}

resource "aws_sns_topic_subscription" "rita_alerts_email" {
  topic_arn = aws_sns_topic.rita_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ── CloudWatch Alarms (all within the 10-alarm free tier) ────────────────────

# 1. CPU spike — warn before OOM or runaway process
resource "aws_cloudwatch_metric_alarm" "rita_cpu_high" {
  alarm_name          = "${local.app_name}-cpu-high"
  alarm_description   = "RITA EC2 CPU > 80% for 10 min — possible runaway process or OOM pressure"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_actions       = [aws_sns_topic.rita_alerts.arn]
  ok_actions          = [aws_sns_topic.rita_alerts.arn]
  dimensions          = { InstanceId = aws_instance.rita.id }
}

# 2. Instance status check failure — triggers AWS auto-recovery + email
resource "aws_cloudwatch_metric_alarm" "rita_status_check" {
  alarm_name          = "${local.app_name}-status-check-failed"
  alarm_description   = "RITA EC2 status check failed — auto-recovery triggered"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "StatusCheckFailed"
  namespace           = "AWS/EC2"
  period              = 60
  statistic           = "Maximum"
  threshold           = 0
  alarm_actions       = [
    "arn:aws:automate:${var.aws_region}:ec2:recover",
    aws_sns_topic.rita_alerts.arn,
  ]
  dimensions          = { InstanceId = aws_instance.rita.id }
}

# 3. Application ERROR log lines — fires when the app logs an error
resource "aws_cloudwatch_log_metric_filter" "rita_errors" {
  name           = "${local.app_name}-error-lines"
  log_group_name = aws_cloudwatch_log_group.rita_app.name
  pattern        = "\"level\": \"error\""
  metric_transformation {
    name      = "RitaErrorCount"
    namespace = "Rita/App"
    value     = "1"
  }
}

resource "aws_cloudwatch_metric_alarm" "rita_app_errors" {
  alarm_name          = "${local.app_name}-app-errors"
  alarm_description   = "RITA application logged ≥ 3 errors in 5 minutes"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "RitaErrorCount"
  namespace           = "Rita/App"
  period              = 300
  statistic           = "Sum"
  threshold           = 3
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.rita_alerts.arn]
  dimensions          = {}
}

# ── SSH Key Pair ──────────────────────────────────────────────────────────────

resource "tls_private_key" "rita" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "rita" {
  key_name   = "${local.app_name}-k3s-key"
  public_key = tls_private_key.rita.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.rita.private_key_pem
  filename        = "${path.module}/generated-key.pem"
  file_permission = "0400"
}

# ── EC2 Compute (K3s Node) ────────────────────────────────────────────────────

resource "aws_instance" "rita" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.rita.id
  vpc_security_group_ids = [aws_security_group.rita.id]
  key_name               = aws_key_pair.rita.key_name
  iam_instance_profile   = aws_iam_instance_profile.rita_ec2.name

  root_block_device {
    # 30 GB stays within the AWS free tier EBS allowance
    volume_size = 30
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -e

    # 1. Data directories — mounted as bind volumes into the RITA container
    mkdir -p /opt/rita_input
    mkdir -p /opt/rita_output
    chown -R ubuntu:ubuntu /opt/rita_input /opt/rita_output

    # 2. Install Docker (official convenience script)
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker ubuntu
    systemctl enable docker
    systemctl start docker

    # 3. Install nginx and configure as reverse proxy to the RITA container
    apt-get install -y nginx
    tee /etc/nginx/sites-available/rita > /dev/null << 'NGINXCONF'
server {
    listen 80;
    server_name _;
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
NGINXCONF
    ln -sf /etc/nginx/sites-available/rita /etc/nginx/sites-enabled/rita
    rm -f /etc/nginx/sites-enabled/default
    systemctl enable nginx
    systemctl start nginx
  EOF

  tags = {
    Name = "${local.app_name}-node"
  }
}

# ── Static IP ─────────────────────────────────────────────────────────────────

resource "aws_eip" "rita" {
  instance = aws_instance.rita.id
  domain   = "vpc"
}
