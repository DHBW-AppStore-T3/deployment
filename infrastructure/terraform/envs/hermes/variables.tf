variable "ssh_public_key" {
  description = "SSH public key for the Hermes deploy keypair. Supplied by CI via TF_VAR_ssh_public_key."
  type        = string
}

# Same rationale as envs/staging and envs/production: scoped to the hosts
# that actually use it (CI runner + operator VPN), not the full campus /48.
variable "ssh_allowed_cidrs_ipv4" {
  description = "IPv4 ranges allowed to reach port 22 (DHBW campus). Inert in practice — see envs/staging for why."
  type        = list(string)
  default     = ["141.72.0.0/16"]

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs_ipv4 : can(cidrhost(c, 0))])
    error_message = "Each entry must be a valid IPv4 CIDR, e.g. 141.72.0.0/16."
  }

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs_ipv4 : trimspace(c) != "0.0.0.0/0"])
    error_message = "ssh_allowed_cidrs_ipv4 must not contain 0.0.0.0/0 - SSH open to the internet."
  }
}

variable "ssh_allowed_cidrs_ipv6" {
  description = "IPv6 ranges allowed to reach port 22 (CI runner + operator VPN)."
  type        = list(string)
  default = [
    "2001:7c0:1b20:c913:1::206/128",
    "2001:7c0:1b20:c126::/64",
  ]

  validation {
    condition     = length(var.ssh_allowed_cidrs_ipv6) > 0
    error_message = "At least one CIDR is required - an empty list locks everyone out of port 22."
  }

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs_ipv6 : can(cidrhost(c, 0))])
    error_message = "Each entry must be a valid IPv6 CIDR, e.g. 2001:7c0:1b20:c126::/64."
  }

  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs_ipv6 : trimspace(c) != "::/0"])
    error_message = "ssh_allowed_cidrs_ipv6 must not contain ::/0 - SSH open to the internet."
  }
}
