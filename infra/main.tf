terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  required_version = ">= 1.5.0"
}

provider "aws" {
  region = var.aws_region
}

module "networking" {
  source = "./modules/networking"

  vpc_cidr             = var.vpc_cidr
  public_subnets_cidr  = var.public_subnets_cidr
  private_subnets_cidr = var.private_subnets_cidr
  availability_zones   = var.availability_zones
  project_name         = var.project_name
  environment          = var.environment

  enable_nat_gateway   = true
  enable_vpc_endpoints = true
  admin_ssh_cidr       = var.admin_ssh_cidr
}

module "compute" {
  source = "./modules/compute"

  vpc_id             = module.networking.vpc_id
  vpc_cidr           = var.vpc_cidr
  public_subnet_ids  = module.networking.public_subnet_ids
  private_subnet_ids = module.networking.private_subnet_ids

  project_name = var.project_name
  environment  = var.environment

  web_image       = var.web_image
  mcp_image       = var.mcp_image
  search_image    = var.search_image
  ingestion_image = var.ingestion_image

  mcp_server_settings_ssm_parameter_name = var.mcp_server_settings_ssm_parameter_name
  mcp_server_settings_ssm_parameter_arn  = var.mcp_server_settings_ssm_parameter_arn
  search_settings_ssm_parameter_name     = var.search_settings_ssm_parameter_name
  search_settings_ssm_parameter_arn      = var.search_settings_ssm_parameter_arn
  ingestion_settings_ssm_parameter_name  = var.ingestion_settings_ssm_parameter_name
  ingestion_settings_ssm_parameter_arn   = var.ingestion_settings_ssm_parameter_arn
  ssm_kms_key_arns                       = var.ssm_kms_key_arns
  private_dns_namespace_name             = var.private_dns_namespace_name

  temporal_instance_type = var.temporal_instance_type
  milvus_instance_type   = var.milvus_instance_type
  ec2_key_name           = var.ec2_key_name
  admin_ssh_cidr         = var.admin_ssh_cidr
}

module "database" {
  source = "./modules/database"

  vpc_id             = module.networking.vpc_id
  private_subnet_ids = module.networking.private_subnet_ids

  project_name = var.project_name
  environment  = var.environment

  db_name             = var.db_name
  db_username         = var.db_username
  db_password         = var.db_password
  deletion_protection = var.db_deletion_protection

  allowed_security_group_ids = [module.compute.app_tasks_sg_id]
}
