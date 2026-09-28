variable "project_name" {
  type        = string
  default     = "flexhub"
  description = "Base name for all resources"
}

variable "location" {
  type        = string
  default     = "East US"
  description = "The Azure region to deploy into"
}