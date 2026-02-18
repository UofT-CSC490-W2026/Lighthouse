variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type = string
}

variable "environment" {
  type    = string
  default = "dev"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "public_subnets_cidr" {
  type = list(string)
  # example: ["10.0.1.0/24", "10.0.2.0/24"]
}

variable "private_subnets_cidr" {
  type = list(string)
  # example: ["10.0.11.0/24", "10.0.12.0/24"]
}

variable "availability_zones" {
  type = list(string)
  # example: ["us-east-1a", "us-east-1b"]
}

# DB
variable "db_name" {
  type = string
}

variable "db_username" {
  type = string
}

variable "db_password" {
  type      = string
  sensitive = true
}

# ECS images (full image URI, e.g. <acct>.dkr.ecr.<region>.amazonaws.com/repo:tag)
variable "mcp_image" {
  type = string
}

variable "worker_image" {
  type = string
}

variable "mcp_container_port" {
  type    = number
  default = 8000
}

# EC2 for Temporal/Milvus
variable "temporal_instance_type" {
  type    = string
  default = "t3.large"
}

variable "milvus_instance_type" {
  type    = string
  default = "t3.large"
}

variable "ec2_key_name" {
  type        = string
  description = "Optional EC2 key pair name for SSH. Leave empty to disable SSH key access."
  default     = ""
}

variable "admin_ssh_cidr" {
  type        = string
  description = "CIDR allowed to SSH into Temporal/Milvus instances (e.g. your IP /32)."
  default     = "0.0.0.0/0"
}
