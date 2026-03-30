output "vpc_id" {
  value = module.networking.vpc_id
}

output "public_subnet_ids" {
  value = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  value = module.networking.private_subnet_ids
}

output "db_endpoint" {
  value = module.database.db_endpoint
}

output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "cluster_name" {
  value = module.compute.cluster_name
}

output "app_tasks_sg_id" {
  value = module.compute.app_tasks_sg_id
}

output "web_url" {
  value = module.compute.web_url
}

output "mcp_base_url" {
  value = module.compute.mcp_base_url
}

output "ingestion_webhook_url" {
  value = module.compute.webhook_url
}

output "db_migrate_task_definition_arn" {
  value = module.compute.db_migrate_task_definition_arn
}

output "milvus_private_ip" {
  value = module.compute.milvus_private_ip
}

output "milvus_instance_id" {
  value = module.compute.milvus_instance_id
}
