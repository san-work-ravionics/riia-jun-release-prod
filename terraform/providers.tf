terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # For future reference: migrate to remote state for production
  # backend "s3" {
  #   bucket = "rita-tfstate-123"
  #   key    = "k3s/terraform.tfstate"
  #   region = "ap-south-1"
  # }
}

provider "aws" {
  region = var.aws_region
}
