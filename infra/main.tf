terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    null = {
      source  = "hashicorp/null"
      version = "~> 3.0"
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

  # for SSH to EC2 (Temporal/Milvus)
  admin_ssh_cidr = var.admin_ssh_cidr
}

module "storage" {
  source = "./modules/storage"

  project_name = var.project_name
  environment  = var.environment

  # var.environment != "prod" in reality but for now true for demo purposes
  force_destroy = true
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

  # Only allow DB access from ECS tasks SGs (created in compute)
  allowed_security_group_ids = [module.compute.ecs_tasks_sg_id, module.compute.worker_tasks_sg_id]
}

module "compute" {
  source = "./modules/compute"

  vpc_id             = module.networking.vpc_id
  vpc_cidr           = var.vpc_cidr
  public_subnet_ids  = module.networking.public_subnet_ids
  private_subnet_ids = module.networking.private_subnet_ids

  project_name = var.project_name
  environment  = var.environment

  # App config
  db_endpoint    = module.database.db_endpoint
  db_name        = var.db_name
  db_username    = var.db_username
  db_password    = var.db_password
  s3_bucket_name = module.storage.bucket_name

  mcp_container_port = var.mcp_container_port

  # EC2 for Temporal/Milvus (separate instances)
  temporal_instance_type = var.temporal_instance_type
  milvus_instance_type   = var.milvus_instance_type
  ec2_key_name           = var.ec2_key_name

  # Networking/SSH
  admin_ssh_cidr = var.admin_ssh_cidr
}
