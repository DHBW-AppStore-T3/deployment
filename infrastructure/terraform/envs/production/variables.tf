variable "ssh_public_key" {
  description = "SSH public key for the production deploy keypair. Supplied by CI via TF_VAR_ssh_public_key."
  type        = string
}

# DHBW campus ranges allowed to reach SSH. Same reasoning as envs/staging:
# committed defaults so a reviewer can see from security_group.tf alone
# whether port 22 is campus-only or open to the world.
variable "ssh_source_cidr_ipv4" {
  description = "IPv4 range allowed to reach port 22 (DHBW campus)."
  type        = string
  default     = "141.72.0.0/16"

  validation {
    condition     = can(cidrhost(var.ssh_source_cidr_ipv4, 0))
    error_message = "ssh_source_cidr_ipv4 must be a valid IPv4 CIDR, e.g. 141.72.0.0/16."
  }
}

variable "ssh_source_cidr_ipv6" {
  description = "IPv6 range allowed to reach port 22 (DHBW campus)."
  type        = string
  default     = "2001:7c0:1b20::/48"

  validation {
    condition     = can(cidrhost(var.ssh_source_cidr_ipv6, 0))
    error_message = "ssh_source_cidr_ipv6 must be a valid IPv6 CIDR, e.g. 2001:7c0:1b20::/48."
  }
}
