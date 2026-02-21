data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

locals {
  project_root     = "${path.root}/.."
  mcp_image_uri    = "${aws_ecr_repository.mcp_service.repository_url}:latest"
  worker_image_uri = "${aws_ecr_repository.pipeline_worker.repository_url}:latest"
}

# --- ECS Cluster
resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.environment}-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# --- ECR repos (optional; you can keep these)
resource "aws_ecr_repository" "mcp_service" {
  name                 = "${var.project_name}-${var.environment}-mcp-service"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

resource "aws_ecr_repository" "pipeline_worker" {
  name                 = "${var.project_name}-${var.environment}-pipeline-worker"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
  image_scanning_configuration { scan_on_push = true }
}

# --- Build and push Docker images to ECR
resource "null_resource" "docker_build_push" {
  triggers = {
    mcp_repo    = aws_ecr_repository.mcp_service.repository_url
    worker_repo = aws_ecr_repository.pipeline_worker.repository_url
  }

  provisioner "local-exec" {
    command = <<-EOT
      aws ecr get-login-password --region ${data.aws_region.current.name} | \
        docker login --username AWS --password-stdin ${data.aws_caller_identity.current.account_id}.dkr.ecr.${data.aws_region.current.name}.amazonaws.com

      docker build -t ${local.mcp_image_uri} -f ${local.project_root}/mcp/Dockerfile ${local.project_root}
      docker push ${local.mcp_image_uri}

      docker build -t ${local.worker_image_uri} -f ${local.project_root}/pipeline/Dockerfile ${local.project_root}
      docker push ${local.worker_image_uri}
    EOT
  }

  depends_on = [
    aws_ecr_repository.mcp_service,
    aws_ecr_repository.pipeline_worker,
  ]
}

# --- CloudWatch logs
resource "aws_cloudwatch_log_group" "mcp" {
  name              = "/ecs/${var.project_name}/${var.environment}/mcp"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${var.project_name}/${var.environment}/worker"
  retention_in_days = 7
}

# --- IAM: ECS execution role (pull images + write logs)
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

# Task role (app permissions: S3 access etc.)
resource "aws_iam_role" "ecs_task_role" {
  name               = "${var.project_name}-${var.environment}-ecs-task-role"
  assume_role_policy = data.aws_iam_policy_document.ecs_task_assume.json
}

data "aws_iam_policy_document" "ecs_task_policy" {
  statement {
    actions = [
      "s3:PutObject", "s3:GetObject", "s3:ListBucket"
    ]
    resources = [
      "arn:aws:s3:::${var.s3_bucket_name}",
      "arn:aws:s3:::${var.s3_bucket_name}/*"
    ]
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

# --- ALB (public) -> MCP tasks (private)
resource "aws_security_group" "alb" {
  name        = "${var.project_name}-${var.environment}-alb-sg"
  description = "ALB ingress"
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

resource "aws_lb" "mcp" {
  name               = "${var.project_name}-${var.environment}-mcp-alb"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids
}

resource "aws_lb_target_group" "mcp" {
  name        = "${var.project_name}-${var.environment}-mcp-tg"
  port        = var.mcp_container_port
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
  load_balancer_arn = aws_lb.mcp.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.mcp.arn
  }
}

# --- ECS task security groups
resource "aws_security_group" "mcp_tasks" {
  name        = "${var.project_name}-${var.environment}-mcp-tasks-sg"
  description = "MCP tasks inbound only from ALB"
  vpc_id      = var.vpc_id

  ingress {
    from_port       = var.mcp_container_port
    to_port         = var.mcp_container_port
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

resource "aws_security_group" "worker_tasks" {
  name        = "${var.project_name}-${var.environment}-worker-tasks-sg"
  description = "Worker tasks: no inbound"
  vpc_id      = var.vpc_id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- ECS task definitions
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
      image     = local.mcp_image_uri
      essential = true
      portMappings = [
        { containerPort = var.mcp_container_port, hostPort = var.mcp_container_port, protocol = "tcp" }
      ]
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "DEBUG", value = "false" },
        { name = "POSTGRES_DSN", value = "postgresql://${var.db_username}:${var.db_password}@${var.db_endpoint}/${var.db_name}" },
        { name = "S3_BUCKET", value = var.s3_bucket_name },
        { name = "TEMPORAL_TARGET_HOST", value = "${aws_instance.temporal.private_ip}:7233" },
        { name = "MILVUS_URI", value = "http://${aws_instance.milvus.private_ip}:19530" }
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

  depends_on = [null_resource.docker_build_push]
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.environment}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_execution_role.arn
  task_role_arn            = aws_iam_role.ecs_task_role.arn

  container_definitions = jsonencode([
    {
      name      = "worker"
      image     = local.worker_image_uri
      essential = true
      environment = [
        { name = "APP_ENV", value = var.environment },
        { name = "DEBUG", value = "false" },
        { name = "POSTGRES_DSN", value = "postgresql://${var.db_username}:${var.db_password}@${var.db_endpoint}/${var.db_name}" },
        { name = "S3_BUCKET", value = var.s3_bucket_name },
        { name = "TEMPORAL_TARGET_HOST", value = "${aws_instance.temporal.private_ip}:7233" },
        { name = "MILVUS_URI", value = "http://${aws_instance.milvus.private_ip}:19530" }
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

  depends_on = [null_resource.docker_build_push]
}

# --- ECS services (private subnets, no public IP)
resource "aws_ecs_service" "mcp" {
  name            = "${var.project_name}-${var.environment}-mcp-svc"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.mcp.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.mcp_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.mcp.arn
    container_name   = "mcp"
    container_port   = var.mcp_container_port
  }

  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.environment}-worker-svc"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.worker_tasks.id]
    assign_public_ip = false
  }
}

# --- EC2 instances: Temporal + Milvus (private)
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
  description = "Temporal/Milvus instances inbound only from VPC + SSH from admin"
  vpc_id      = var.vpc_id

  # SSH
  dynamic "ingress" {
    for_each = var.ec2_key_name != "" ? [1] : []
    content {
      from_port   = 22
      to_port     = 22
      protocol    = "tcp"
      cidr_blocks = [var.admin_ssh_cidr]
    }
  }

  # Temporal frontend (from within VPC)
  ingress {
    from_port   = 7233
    to_port     = 7233
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Milvus port (from within VPC)
  ingress {
    from_port   = 19530
    to_port     = 19530
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # Optional: Milvus health/metrics, etc. Add later if needed.

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Temporal instance user_data (docker compose)
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
    version: "3.8"
    services:
      postgres:
        image: postgres:17
        environment:
          POSTGRES_PASSWORD: temporal
          POSTGRES_USER: temporal
          POSTGRES_DB: temporal
        volumes:
          - pgdata:/var/lib/postgresql/data
        restart: unless-stopped

      temporal:
        image: temporalio/auto-setup:1.25
        environment:
          DB: postgresql
          DB_PORT: 5432
          POSTGRES_USER: temporal
          POSTGRES_PWD: temporal
          POSTGRES_SEEDS: postgres
        depends_on:
          - postgres
        ports:
          - "7233:7233"
        restart: unless-stopped

      temporal-ui:
        image: temporalio/ui:2.28.0
        environment:
          TEMPORAL_ADDRESS: temporal:7233
        ports:
          - "8080:8080"
        depends_on:
          - temporal
        restart: unless-stopped

    volumes:
      pgdata:
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
    version: "3.8"
    services:
      etcd:
        image: quay.io/coreos/etcd:v3.5.5
        environment:
          - ETCD_AUTO_COMPACTION_MODE=revision
          - ETCD_AUTO_COMPACTION_RETENTION=1000
          - ETCD_QUOTA_BACKEND_BYTES=4294967296
          - ETCD_SNAPSHOT_COUNT=50000
        command: >
          etcd
          -advertise-client-urls=http://0.0.0.0:2379
          -listen-client-urls=http://0.0.0.0:2379
          -data-dir=/etcd
        volumes:
          - etcd:/etcd
        restart: unless-stopped

      minio:
        image: minio/minio:RELEASE.2024-01-16T16-07-38Z
        environment:
          MINIO_ACCESS_KEY: minioadmin
          MINIO_SECRET_KEY: minioadmin
        command: server /minio_data --console-address ":9001"
        ports:
          - "9000:9000"
          - "9001:9001"
        volumes:
          - minio:/minio_data
        restart: unless-stopped

      milvus:
        image: milvusdb/milvus:v2.4.9
        command: ["milvus", "run", "standalone"]
        environment:
          ETCD_ENDPOINTS: etcd:2379
          MINIO_ADDRESS: minio:9000
        ports:
          - "19530:19530"
          - "9091:9091"
        depends_on:
          - etcd
          - minio
        restart: unless-stopped

    volumes:
      etcd:
      minio:
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
