variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }

variable "project_name" { type = string }
variable "environment"  { type = string }

variable "db_name" { type = string }
variable "db_username" { type = string }
variable "db_password" {
  type      = string
  sensitive = true
}

variable "allowed_security_group_ids" {
  type        = list(string)
  description = "Security groups allowed to connect to Postgres"
  default     = []
}
