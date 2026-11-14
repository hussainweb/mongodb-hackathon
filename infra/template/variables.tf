variable "worker_count" {
  type        = number
  description = "Number of worker containers to run"
  default     = 1
}

variable "max_rps" {
  type        = number
  description = "Per-worker requests per second limit"
  default     = 120
}

variable "service_name" {
  type        = string
  description = "Logical service name"
  default     = "payments-webhook"
}

variable "env_tier" {
  type        = string
  description = "Deployment environment tier (staging, canary, production)"
  default     = "staging"
}

variable "callback_uri" {
  type        = string
  description = "Downstream callback URI"
  default     = "https://hooks.example.internal/v1/ingest"
}

variable "worker_image" {
  type        = string
  description = "Docker image tag for worker containers"
  default     = "finishline-worker:v1"
}

variable "use_v2_env" {
  type        = bool
  description = "Use v2 env variable names (MAX_RPS, CALLBACK_URI)"
  default     = false
}

variable "silent_drop_first_probe" {
  type        = bool
  description = "Simulate silent drop on initial health probe"
  default     = false
}

variable "run_prefix" {
  type        = string
  description = "Unique container name prefix"
  default     = "finishline-demo"
}

variable "repo_slug" {
  type        = string
  description = "Source repository slug"
  default     = "dry-run/payments-infra"
}
