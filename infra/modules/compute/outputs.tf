output "alb_dns_name" {
  value = aws_lb.public.dns_name
}

output "cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "app_tasks_sg_id" {
  value = aws_security_group.app_tasks.id
}

output "web_url" {
  value = "http://${aws_lb.public.dns_name}"
}

output "mcp_base_url" {
  value = "http://${aws_lb.public.dns_name}"
}

output "webhook_url" {
  value = "http://${aws_lb.public.dns_name}/webhook"
}

output "db_migrate_task_definition_arn" {
  value = aws_ecs_task_definition.db_migrate.arn
}

output "temporal_private_ip" {
  value = aws_instance.temporal.private_ip
}

output "milvus_private_ip" {
  value = aws_instance.milvus.private_ip
}
