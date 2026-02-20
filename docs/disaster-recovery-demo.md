# Disaster Recovery Demo Runbook

Use this script during your screen recording to clearly show deletion and IaC-based restoration of production.

## Demo Goal

Prove that your team can:
- Delete production infrastructure
- Recreate it using Terraform
- Restore application functionality
- Re-establish configuration and security controls

## 1. Baseline: Show Production Is Healthy

### 1.1 Terraform checks


## 4. Post-Restore Verification (Grading-Critical)

### 4.1 Verify deployed apps / data processing services


## 4. Post-Restore Verification (Grading-Critical)

### 4.1 Verify deployed apps / data processing services

```bash
cd infra
terraform init
terraform validate
terraform plan -var-file=terraform.tfvars
terraform output
```

### 1.2 App health check

```bash
ALB=$(terraform output -raw alb_dns_name)
curl -i "http://$ALB/health"
```

### 1.3 AWS Console views to show

- ECS cluster and running services (`mcp`, `worker`)
- ALB and target group healthy targets
- RDS instance status `Available`
- EC2 instances for Temporal and Milvus
- S3 bucket for data lake
- IAM roles and security groups (especially DB access rules)

## 2. Simulate Disaster: Delete Production

```bash
cd infra
terraform destroy -var-file=terraform.tfvars -auto-approve
```

### 2.1 Console verification of deletion

Show that the Terraform-managed resources are deleted:
- ECS services/cluster
- ALB + target groups
- RDS instance
- EC2 instances
- Terraform-managed networking components

## 3. Restore Production with IaC

```bash
cd infra
terraform init
terraform apply -var-file=terraform.tfvars -auto-approve
terraform output
```

## 4. Post-Restore Verification (Grading-Critical)\
### 4.1 Verify deployed apps / data processing services

```bash
ALB=$(terraform -chdir=infra output -raw alb_dns_name)
curl -i "http://$ALB/health"
```

Show in Console:
- ECS tasks running for `mcp` and `worker`
- CloudWatch logs receiving entries
roups for ALB, ECS tasks, DB
- VPC/subnets/NAT/VPC endpoints

### 4.2 Verify database systems and data

Show in Console:
- RDS status `Available`
- DB endpoint present

Optional stronger proof:
- Insert a known test record before deletion
- Show record again after restore (or explain expected loss if no backup strategy exists)

### 4.3 Verify configuration settings

Show:
- `infra/terraform.tfvars` values used (mask secrets on recording)
- Relevant Terraform modules (`infra/main.tf`, `infra/modules/*`)

Then prove no drift:

```bash
terraform -chdir=infra plan -var-file=terraform.tfvars
```

Expected result: no changes.

### 4.4 Verify access controls and security settings

Show in Console:
- IAM roles for ECS execution/task
- Security groups for ALB, ECS tasks, DB
- VPC/subnets/NAT/VPC endpoints

## 5. Demo Checklist (Use This Verbatim)

- [ ] Data processing services/deployed applications shown before and after restore
- [ ] Database system shown before and after restore
- [ ] Configuration settings shown from Terraform code/vars
- [ ] Access controls/security settings shown (IAM + SG + network)
- [ ] Functional verification shown (`curl /health`, healthy targets, running tasks)
- [ ] Clean Terraform state shown (`terraform plan` reports no changes)

## 6. Fast Command Block (Copy/Paste)

```bash
cd infra
terraform init
terraform validate
terraform plan -var-file=terraform.tfvars
terraform output

ALB=$(terraform output -raw alb_dns_name)
curl -i "http://$ALB/health"

terraform destroy -var-file=terraform.tfvars -auto-approve

terraform init
terraform apply -var-file=terraform.tfvars -auto-approve
terraform output

ALB=$(terraform output -raw alb_dns_name)
curl -i "http://$ALB/health"

terraform plan -var-file=terraform.tfvars
```

## Notes

- This runbook targets your current `prod` tfvars setup.
- Be careful to mask sensitive values (`db_password`, account IDs) during recording if required by your course policy.
operation
