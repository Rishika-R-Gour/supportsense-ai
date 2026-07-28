# Credits-limited AWS staging

This profile is for a personal AWS Free Plan account with promotional credits.
It deliberately does **not** claim to be highly available production.

It creates:

- one Free Plan-eligible `t3.small` EC2 instance in the default VPC;
- 20 GB of encrypted `gp3` storage;
- an account-level monthly AWS Budget;
- an SSM instance role, with no SSH port;
- a security group exposing HTTP only to `allowed_cidr`;
- automatic daily instance shutdown and standard (non-unlimited) CPU credits.

It does not create NAT gateways, load balancers, ECS, RDS, ElastiCache,
Elastic IPs, Route 53 zones, or paid observability services. PostgreSQL, Redis,
Chroma, the API, and the frontend run as containers on the single instance.

## Safety limitations

- Use synthetic/demo data only.
- The endpoint is HTTP-only and restricted to your IP.
- Rollout is locked to `shadow`; support tools are disabled.
- Stopping the instance changes its public IP and DNS name.
- The EC2 instance and its single EBS volume are failure domains.

## Apply

From AWS CloudShell or a workstation with AWS CLI and Terraform:

```bash
cd infra/terraform-free
terraform init
terraform plan \
  -var='allowed_cidr=YOUR_PUBLIC_IP/32' \
  -var='budget_email=YOUR_EMAIL'
terraform apply \
  -var='allowed_cidr=YOUR_PUBLIC_IP/32' \
  -var='budget_email=YOUR_EMAIL'
```

Review the plan before approving it. After apply, use `terraform output
public_url`. The first boot builds six containers and can take several minutes.

Use Session Manager rather than SSH:

```bash
terraform output -raw ssm_session_command
```

The generated API key is stored only on the instance at
`/opt/supportsense/repository/.env.free-tier`.

## Cost controls

The default budget is USD 10/month. Email notifications fire at 80% actual
spend and 100% forecasted spend. The instance stops daily at 02:00 UTC.
Manually start it only when demonstrating or testing, then stop it again.

Destroy the profile when finished:

```bash
terraform destroy \
  -var='allowed_cidr=YOUR_PUBLIC_IP/32' \
  -var='budget_email=YOUR_EMAIL'
```
