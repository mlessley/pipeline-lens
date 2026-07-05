data "aws_eks_cluster_auth" "this" {
  name = module.eks.cluster_name
}

provider "kubernetes" {
  host                   = module.eks.cluster_endpoint
  cluster_ca_certificate = base64decode(module.eks.cluster_certificate_authority_data)
  token                  = data.aws_eks_cluster_auth.this.token
}

resource "kubernetes_deployment" "pipeline-lens" {
  metadata {
    name      = var.project_name
    namespace = "default"
    labels = {
      app = var.project_name
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = {
        app = var.project_name
      }
    }

    template {
      metadata {
        labels = {
          app = var.project_name
        }
      }

      spec {
        container {
          name = var.project_name
          # Bootstrap placeholder so the Deployment exists before the first
          # real CI push. ci.yml (Task 16) replaces this via `kubectl set
          # image` on every push to main — this value is never read again
          # after the first successful CI run.
          image = "public.ecr.aws/docker/library/nginx:stable"
        }
      }
    }
  }

  depends_on = [module.eks]
}
