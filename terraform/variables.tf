# ── AWS Connection ────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy K3s cluster into"
  type        = string
  default     = "ap-south-1"
}

# ── Environment ───────────────────────────────────────────────────────────────

variable "rita_env" {
  description = "Runtime environment (development | staging | production)"
  type        = string
  default     = "staging"
}

variable "jwt_secret" {
  description = "JWT signing secret — minimum 32 characters"
  type        = string
  sensitive   = true
}

# ── Google OAuth Integration ──────────────────────────────────────────────────

variable "google_client_id" {
  description = "Google OAuth 2.0 Client ID for user logins"
  type        = string
  default     = "CHANGE_ME"
}

variable "google_client_secret" {
  description = "Google OAuth 2.0 Client Secret for user logins"
  type        = string
  sensitive   = true
  default     = "CHANGE_ME"
}

# ── Networking ────────────────────────────────────────────────────────────────

variable "vpc_cidr" {
  description = "CIDR block for the AWS VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "subnet_cidr" {
  description = "CIDR block for the public subnet where the EC2 wrapper sits"
  type        = string
  default     = "10.0.1.0/24"
}

# ── EC2 Configuration ─────────────────────────────────────────────────────────

variable "instance_type" {
  description = "EC2 instance size. t3.micro is free-tier eligible in ap-south-1 (1 vCPU, 1 GB RAM)."
  type        = string
  default     = "t3.micro"
}
