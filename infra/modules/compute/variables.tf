variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }

variable "project_name" { type = string }
variable "environment" { type = string }

variable "web_image" { type = string }
variable "mcp_image" { type = string }
variable "search_image" { type = string }
variable "ingestion_image" { type = string }

variable "mcp_server_settings_ssm_parameter_name" { type = string }
variable "mcp_server_settings_ssm_parameter_arn" { type = string }
variable "search_settings_ssm_parameter_name" { type = string }
variable "search_settings_ssm_parameter_arn" { type = string }
variable "ingestion_settings_ssm_parameter_name" { type = string }
variable "ingestion_settings_ssm_parameter_arn" { type = string }

variable "ssm_kms_key_arns" {
  type    = list(string)
  default = ["*"]
}

variable "private_dns_namespace_name" {
  type    = string
  default = ""
}

variable "temporal_instance_type" { type = string }
variable "milvus_instance_type" { type = string }

variable "ec2_key_name" {
  type    = string
  default = ""
}

variable "admin_ssh_cidr" {
  type    = string
  default = "0.0.0.0/0"
}
