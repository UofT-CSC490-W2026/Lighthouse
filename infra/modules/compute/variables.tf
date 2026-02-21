variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "public_subnet_ids" { type = list(string) }
variable "private_subnet_ids" { type = list(string) }

variable "project_name" { type = string }
variable "environment" { type = string }

variable "db_endpoint" { type = string }
variable "db_name" { type = string }
variable "db_username" { type = string }
variable "db_password" {
  type      = string
  sensitive = true
}
variable "s3_bucket_name" { type = string }

variable "mcp_container_port" {
  type    = number
  default = 8000
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
