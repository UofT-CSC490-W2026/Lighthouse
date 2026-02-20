output "alb_dns_name" {
  value = aws_lb.mcp.dns_name
}

output "ecs_tasks_sg_id" {
  value = aws_security_group.mcp_tasks.id
}

output "worker_tasks_sg_id" {
  value = aws_security_group.worker_tasks.id
}

output "temporal_private_ip" {
  value = aws_instance.temporal.private_ip
}

output "milvus_private_ip" {
  value = aws_instance.milvus.private_ip
}
