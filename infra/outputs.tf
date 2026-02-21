output "vpc_id" {
  value = module.networking.vpc_id
}

output "public_subnet_ids" {
  value = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  value = module.networking.private_subnet_ids
}

output "s3_bucket_name" {
  value = module.storage.bucket_name
}

output "db_endpoint" {
  value = module.database.db_endpoint
}

output "alb_dns_name" {
  value = module.compute.alb_dns_name
}

output "temporal_private_ip" {
  value = module.compute.temporal_private_ip
}

output "milvus_private_ip" {
  value = module.compute.milvus_private_ip
}
