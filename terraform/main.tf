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

    # 3. Log in to GHCR anonymously (public image — no credentials needed)
    #    If the GHCR package is private, pass a token here instead.
    systemctl enable docker
    systemctl start docker
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
