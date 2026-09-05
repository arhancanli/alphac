variable "region" {
  description = "Single region for Foundry compute, database and object storage."
  type        = string
  default     = "nyc3"
}

variable "project_name" {
  description = "Dedicated DigitalOcean project name."
  type        = string
  default     = "canli-foundry-production"
}

variable "research_vpc_cidr" {
  description = "Private research network. It must not overlap execution infrastructure."
  type        = string
  default     = "10.44.0.0/20"
}

variable "holdout_vpc_cidr" {
  description = "Independent holdout network with no VPC peering."
  type        = string
  default     = "10.45.0.0/24"
}

variable "research_node_size" {
  type    = string
  default = "s-2vcpu-4gb"
}

variable "holdout_node_size" {
  type    = string
  default = "s-1vcpu-1gb"
}

variable "postgres_size" {
  type    = string
  default = "db-s-1vcpu-1gb"
}

variable "postgres_version" {
  type    = string
  default = "18"
}

variable "spaces_bucket_prefix" {
  description = "Globally unique, lowercase prefix for the three private buckets."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{8,39}$", var.spaces_bucket_prefix))
    error_message = "spaces_bucket_prefix must be 9 to 40 lowercase letters, digits or hyphens."
  }
}

variable "enable_ephemeral_bastion" {
  description = "Temporary maintenance path. Keep false outside a dated maintenance window."
  type        = bool
  default     = false
}

variable "operator_cidr" {
  description = "Exact operator IPv4 CIDR used only when the ephemeral bastion is enabled."
  type        = string
  default     = ""

  validation {
    condition = (
      !var.enable_ephemeral_bastion
      || can(cidrhost(var.operator_cidr, 0))
    )
    error_message = "operator_cidr must be a valid CIDR when the bastion is enabled."
  }
}

variable "operator_ssh_key_fingerprints" {
  description = "Dedicated reviewed Foundry SSH keys. They are installed on private hosts at creation and attached to an ephemeral bastion only when enabled."
  type        = list(string)
  default     = []

  validation {
    condition = (
      length(var.operator_ssh_key_fingerprints) > 0
      && alltrue([
        for fingerprint in var.operator_ssh_key_fingerprints : length(trimspace(fingerprint)) > 0
      ])
    )
    error_message = "At least one non-empty dedicated Foundry SSH key fingerprint is required before private hosts are created."
  }
}
