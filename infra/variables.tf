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
}

variable "private_subnets_cidr" {
  type = list(string)
}

variable "availability_zones" {
  type = list(string)
}

variable "web_image" {
  type = string
}

variable "mcp_image" {
  type = string
}

variable "search_image" {
  type = string
}

variable "ingestion_image" {
  type = string
}

variable "mcp_server_settings_ssm_parameter_name" {
  type = string
}

variable "mcp_server_settings_ssm_parameter_arn" {
  type = string
}

variable "search_settings_ssm_parameter_name" {
  type = string
}

variable "search_settings_ssm_parameter_arn" {
  type = string
}

variable "ingestion_settings_ssm_parameter_name" {
  type = string
}

variable "ingestion_settings_ssm_parameter_arn" {
  type = string
}

variable "ssm_kms_key_arns" {
  type    = list(string)
  default = ["*"]
}

variable "private_dns_namespace_name" {
  type    = string
  default = ""
}

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

variable "db_deletion_protection" {
  type        = bool
  description = "Enable RDS deletion protection. Set false for planned teardown demos."
  default     = true
}

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
  description = "CIDR allowed to SSH into Temporal/Milvus instances when SSH access is enabled."
}
