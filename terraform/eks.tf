module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 20.0"

  cluster_name    = var.project_name
  cluster_version = "1.36"

  # Module default is public_access = false / private_access = true, which
  # blocks Terraform (running outside the VPC) from reaching the API server
  # to manage the kubernetes_deployment resource in k8s.tf.
  cluster_endpoint_public_access = true

  # Module default is false, which leaves the applying identity with no
  # Kubernetes RBAC access — the kubernetes_deployment resource in k8s.tf
  # would 403 even with the endpoint reachable.
  enable_cluster_creator_admin_permissions = true

  vpc_id     = data.aws_vpc.default.id
  subnet_ids = data.aws_subnets.default.ids

  eks_managed_node_groups = {
    default = {
      instance_types = ["t3.small"]
      min_size       = 1
      max_size       = 2
      desired_size   = 1
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }

  # us-east-1e does not support EKS control plane ENIs; excluding it here
  # avoids UnsupportedAvailabilityZoneException on cluster creation.
  filter {
    name   = "availability-zone"
    values = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1d", "us-east-1f"]
  }
}
