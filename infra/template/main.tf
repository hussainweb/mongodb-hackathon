terraform {
  required_version = ">= 1.6.0"

  required_providers {
    docker = {
      source  = "kreuzwerker/docker"
      version = "~> 3.0"
    }
  }
}

provider "docker" {}

resource "docker_container" "worker" {
  count   = var.worker_count
  name    = "${var.run_prefix}-worker-${count.index + 1}"
  image   = var.worker_image
  restart = "no"

  ports {
    internal = 8080
    ip       = "127.0.0.1"
  }

  env = compact([
    "WORKER_INDEX=${count.index}",
    "SERVICE_NAME=${var.service_name}",
    "ENV_TIER=${var.env_tier}",
    "SILENT_DROP_FIRST_PROBE=${var.silent_drop_first_probe ? "1" : "0"}",
    var.use_v2_env ? "MAX_RPS=${var.max_rps}" : "RATE_LIMIT=${var.max_rps}",
    var.use_v2_env ? "CALLBACK_URI=${var.callback_uri}" : "WEBHOOK_URL=${var.callback_uri}",
  ])

  labels {
    label = "finishline.managed"
    value = "true"
  }

  labels {
    label = "finishline.repo"
    value = var.repo_slug
  }

  labels {
    label = "finishline.prefix"
    value = var.run_prefix
  }
}
