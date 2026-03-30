data "aws_region" "current" {}

locals {
  private_dns_namespace = var.private_dns_namespace_name != "" ? var.private_dns_namespace_name : "${var.project_name}-${var.environment}.local"

  temporal_address      = "${aws_instance.temporal.private_ip}:7233"
  milvus_uri            = "http://${aws_instance.milvus.private_ip}:19530"
  search_service_url    = "http://search.${local.private_dns_namespace}:8002"
  ingestion_service_url = "http://ingestion.${local.private_dns_namespace}:8001"
}

resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "web" {
  name              = "/ecs/${var.project_name}/${var.environment}/web"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/ecs/${var.project_name}/${var.environment}/mcp"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "search" {
  name              = "/ecs/${var.project_name}/${var.environment}/search"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "ingestion" {
  name              = "/ecs/${var.project_name}/${var.environment}/ingestion"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}/${var.environment}/ingestion-worker"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "db_migrate" {
  name              = "/ecs/${var.project_name}/${var.environment}/db-migrate"
  retention_in_days = 7
}

data "aws_iam_policy_document" "ecs_task_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_execution_role" {
  name               = "${var.project_name}-${var.environment}-ecs-exec-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

resource "aws_iam_role_policy_attachment" "ecs_exec_attach" {
  role       = aws_iam_role.ecs_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "ecs_task_role" {
  name               = "${var.project_name}-${var.environment}-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

data "aws_iam_policy_document" "ecs_task_policy" {
  statement {
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      var.mcp_server_settings_ssm_parameter_arn,
      var.search_settings_ssm_parameter_arn,
      var.ingestion_settings_ssm_parameter_arn,
    ]
  }

  statement {
    actions   = ["kms:Decrypt"]
    resources = var.ssm_kms_key_arns
  }
}

resource "aws_iam_policy" "ecs_task_policy" {
  name   = "${var.project_name}-${var.environment}-ecs-task-policy"
  policy = data.aws_iam_policy_document.ecs_task_policy.json
}

resource "aws_iam_role_policy_attachment" "ecs_task_attach" {
  role       = aws_iam_role.ecs_task_role.name
  policy_arn = aws_iam_policy.ecs_task_policy.arn
}

resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "Public ALB ingress"
  vpc_id      = var.vpc_id

  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "app_tasks" {
  name        = "${var.project_name}-${var.environment}-app-tasks-sg"
  description = "Application ECS task ingress from the ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    from_port       = 8001
    to_port         = 8001
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "public" {
  name               = "${var.project_name}-${var.environment}-public"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "web" {
  name        = "${var.project_name}-${var.environment}-web"
  port        = 80
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/"
    interval            = 20
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200-399"
  }
}

resource "aws_lb_target_group" "mcp" {
  name        = "${var.project_name}-${var.environment}-mcp"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    interval            = 20
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200-399"
  }
}

resource "aws_lb_target_group" "ingestion" {
  name        = "${var.project_name}-${var.environment}-ingest"
  port        = 8001
  protocol    = "HTTP"
  vpc_id      = var.vpc_id
  target_type = "ip"

  health_check {
    path                = "/health"
    interval            = 20
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
    matcher             = "200-399"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.public.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_lb_listener_rule" "mcp" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mcp.arn
  }

  condition {
    path_pattern {
      values = ["/health", "/v1/*", "/mcp", "/mcp/*"]
    }
  }
}

resource "aws_lb_listener_rule" "ingestion_webhook" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 20

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.ingestion.arn
  }

  condition {
    path_pattern {
      values = ["/webhook"]
    }
  }
}

resource "aws_service_discovery_private_dns_namespace" "main" {
  name = local.private_dns_namespace
  vpc  = var.vpc_id
}

resource "aws_service_discovery_service" "search" {
  name = "search"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }
}

resource "aws_service_discovery_service" "ingestion" {
  name = "ingestion"

  dns_config {
    namespace_id = aws_service_discovery_private_dns_namespace.main.id

    dns_records {
      ttl  = 10
      type = "A"
    }

    routing_policy = "MULTIVALUE"
  }
}

resource "aws_ecs_task_definition" "web" {
  family                   = "${var.project_name}-${var.environment}-web"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "web"
      image     = var.web_image
      essential = true
      portMappings = [
        { containerPort = 80, hostPort = 80, protocol = "tcp" }
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.web.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "mcp" {
  family                   = "${var.project_name}-${var.environment}-mcp"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "mcp"
      image     = var.mcp_image
      essential = true
      portMappings = [
        { containerPort = 8000, hostPort = 8000, protocol = "tcp" }
      ]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "DEBUG", value = "false" },
        { name = "MCP_SERVER_SETTINGS_SSM_PARAMETER", value = var.mcp_server_settings_ssm_parameter_name },
        { name = "SEARCH_SERVICE_URL", value = local.search_service_url },
        { name = "INGESTION_SERVICE_URL", value = local.ingestion_service_url },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.mcp.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "search" {
  family                   = "${var.project_name}-${var.environment}-search"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "search"
      image     = var.search_image
      essential = true
      portMappings = [
        { containerPort = 8002, hostPort = 8002, protocol = "tcp" }
      ]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "SEARCH_SETTINGS_SSM_PARAMETER", value = var.search_settings_ssm_parameter_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.search.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "ingestion" {
  family                   = "${var.project_name}-${var.environment}-ingestion"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "ingestion"
      image     = var.ingestion_image
      essential = true
      portMappings = [
        { containerPort = 8001, hostPort = 8001, protocol = "tcp" }
      ]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "INGESTION_SETTINGS_SSM_PARAMETER", value = var.ingestion_settings_ssm_parameter_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ingestion.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "ingestion_worker" {
  family                   = "${var.project_name}-${var.environment}-ingestion-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "ingestion-worker"
      image     = var.ingestion_image
      essential = true
      command   = ["python", "-m", "ingestion.temporal.worker"]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "INGESTION_SETTINGS_SSM_PARAMETER", value = var.ingestion_settings_ssm_parameter_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.worker.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_task_definition" "db_migrate" {
  family                   = "${var.project_name}-${var.environment}-db-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "db-migrate"
      image     = var.ingestion_image
      essential = true
      command   = ["alembic", "-c", "packages/db/alembic.ini", "upgrade", "head"]
      environment = [
        { name = "AWS_REGION", value = data.aws_region.current.name },
        { name = "INGESTION_SETTINGS_SSM_PARAMETER", value = var.ingestion_settings_ssm_parameter_name },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.db_migrate.name
          awslogs-region        = data.aws_region.current.name
          awslogs-stream-prefix = "ecs"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "web" {
  name            = "${var.project_name}-${var.environment}-web"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.web.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 80
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "mcp" {
  name            = "${var.project_name}-${var.environment}-mcp"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp.arn
    container_name   = "mcp"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener_rule.mcp]
}

resource "aws_ecs_service" "search" {
  name            = "${var.project_name}-${var.environment}-search"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.search.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app_tasks.id]
    assign_public_ip = false
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.search.arn
    container_name = "search"
    container_port = 8002
  }
}

resource "aws_ecs_service" "ingestion" {
  name            = "${var.project_name}-${var.environment}-ingestion"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ingestion.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.ingestion.arn
    container_name   = "ingestion"
    container_port   = 8001
  }

  service_registries {
    registry_arn   = aws_service_discovery_service.ingestion.arn
    container_name = "ingestion"
    container_port = 8001
  }

  depends_on = [aws_lb_listener_rule.ingestion_webhook]
}

resource "aws_ecs_service" "ingestion_worker" {
  name            = "${var.project_name}-${var.environment}-ingestion-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.ingestion_worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.app_tasks.id]
    assign_public_ip = false
  }
}

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
}

resource "aws_security_group" "stateful_ec2" {
  name        = "${var.project_name}-${var.environment}-stateful-sg"
  description = "Temporal and Milvus ingress from inside the VPC and optional SSH"
  vpc_id      = var.vpc_id

  dynamic "ingress" {
    for_each = var.ec2_key_name != "" ? [1] : []

    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [var.admin_ssh_cidr]
    }
  }

  ingress {
    from_port   = 7233
    to_port     = 7233
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  ingress {
    from_port   = 19530
    to_port     = 19530
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

locals {
  temporal_user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    dnf update -y
    dnf install -y docker docker-compose-plugin
    systemctl enable docker
    systemctl start docker

    mkdir -p /opt/temporal
    cat >/opt/temporal/docker-compose.yml <<'YML'
    services:
      temporal:
        image: temporalio/temporal:latest
        ports:
          - "7233:7233"
          - "8233:8233"
        volumes:
          - temporal_data:/home/temporal
        command: ["server", "start-dev", "--ip", "0.0.0.0", "--db-filename", "/home/temporal/temporal.db"]
        restart: unless-stopped

    volumes:
      temporal_data:
    YML

    docker compose -f /opt/temporal/docker-compose.yml up -d
  EOF

  milvus_user_data = <<-EOF
    #!/bin/bash
    set -euxo pipefail

    dnf update -y
    dnf install -y docker docker-compose-plugin
    systemctl enable docker
    systemctl start docker

    mkdir -p /opt/milvus
    cat >/opt/milvus/docker-compose.yml <<'YML'
    services:
      etcd:
        image: quay.io/coreos/etcd:v3.5.25
        environment:
          ETCD_AUTO_COMPACTION_MODE: revision
          ETCD_AUTO_COMPACTION_RETENTION: "1000"
          ETCD_QUOTA_BACKEND_BYTES: "4294967296"
          ETCD_SNAPSHOT_COUNT: "50000"
        command: >
          etcd
          --advertise-client-urls=http://etcd:2379
          --listen-client-urls=http://0.0.0.0:2379
          --data-dir=/etcd
        volumes:
          - etcd_data:/etcd
        restart: unless-stopped

      minio:
        image: minio/minio:RELEASE.2024-05-28T17-19-04Z
        environment:
          MINIO_ACCESS_KEY: minioadmin
          MINIO_SECRET_KEY: minioadmin
        command: minio server /minio_data --console-address ":9001"
        volumes:
          - minio_data:/minio_data
        restart: unless-stopped

      milvus:
        image: milvusdb/milvus:v2.6.12
        command: ["milvus", "run", "standalone"]
        environment:
          ETCD_ENDPOINTS: etcd:2379
          MINIO_ADDRESS: minio:9000
          MINIO_REGION: us-east-1
        ports:
          - "19530:19530"
          - "9091:9091"
        volumes:
          - milvus_data:/var/lib/milvus
        depends_on:
          - etcd
          - minio
        restart: unless-stopped

    volumes:
      etcd_data:
      minio_data:
      milvus_data:
    YML

    docker compose -f /opt/milvus/docker-compose.yml up -d
  EOF
}

resource "aws_instance" "temporal" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.temporal_instance_type
  subnet_id              = var.private_subnet_ids[0]
  vpc_security_group_ids = [aws_security_group.stateful_ec2.id]
  key_name               = var.ec2_key_name != "" ? var.ec2_key_name : null
  user_data              = local.temporal_user_data

  tags = {
    Name = "${var.project_name}-${var.environment}-temporal"
  }
}

resource "aws_instance" "milvus" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.milvus_instance_type
  subnet_id              = element(var.private_subnet_ids, 1)
  vpc_security_group_ids = [aws_security_group.stateful_ec2.id]
  key_name               = var.ec2_key_name != "" ? var.ec2_key_name : null
  user_data              = local.milvus_user_data

  tags = {
    Name = "${var.project_name}-${var.environment}-milvus"
  }
}
