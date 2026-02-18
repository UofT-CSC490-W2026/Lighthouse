variable "vpc_cidr" { type = string }

variable "public_subnets_cidr" {
  type = list(string)
}

variable "private_subnets_cidr" {
  type = list(string)
}

variable "availability_zones" {
  type = list(string)
}

variable "project_name" { type = string }
variable "environment"  { type = string }

variable "enable_nat_gateway" {
  type    = bool
  default = true
}

variable "enable_vpc_endpoints" {
  type    = bool
  default = true
}

variable "admin_ssh_cidr" {
  type    = string
  default = "0.0.0.0/0"
}
