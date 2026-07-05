variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  description = "Also used as the ECR repo name and K8s Deployment/container name — must equal the GitHub repo's short name, since the correlation workflow (Task 11) derives its ECR/K8s lookup key from RepoEvent.repo.split('/')[-1]."
  type        = string
  default     = "pipeline-lens"
}

variable "github_repo" {
  description = "GitHub repo in 'owner/name' form, for OIDC trust"
  type        = string
}
