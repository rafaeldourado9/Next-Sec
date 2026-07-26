variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "project" {
  description = "Nome do projeto (usado em tags e resource names)"
  type        = string
  default     = "vms-dev"
}
