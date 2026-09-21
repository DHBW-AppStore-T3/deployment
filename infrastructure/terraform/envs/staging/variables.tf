variable "ssh_public_key" {
  description = "SSH public key for the staging deploy keypair. Supplied by CI via TF_VAR_ssh_public_key (derived from the SSH_PRIVATE_KEY secret)."
  type        = string
}

# Who may reach port 22.
#
# Scoped to the hosts that actually use it, rather than to the campus
# allocation 2001:7c0:1b20::/48. A /48 spans 65536 /64 networks and includes
# the tenant network this project's own instances draw addresses from, so as
# an SSH source it is considerably broader than "campus" suggests.
#
# The entries are the CI runner, which drives the Ansible deploy, and the
# operator VPN gateway. They are separate list entries on purpose, so either
# can be adjusted without widening the other.
#
# Committed as defaults for the same reason as before: a reviewer reading
# security_group.tf must be able to tell whether port 22 is scoped, and
# widening it should be an auditable diff rather than an invisible env var.
# Still overridable via TF_VAR_ssh_allowed_cidrs_ipv6.
#
# IPv4 is left at the campus range deliberately. These hosts hold only
# RFC1918 IPv4 addresses, which campus IPv4 has no route to, so that rule
# admits nothing in practice - narrowing it would imply a protection it is
# not actually providing. IPv6 is the only path that reaches sshd.
variable "ssh_allowed_cidrs_ipv4" {
  description = "IPv4 ranges allowed to reach port 22 (DHBW campus). See the note above: inert in practice."
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

  # Enforced at plan time rather than by a linter, so it cannot be waived by
  # skipping a lint step.
  validation {
    condition     = alltrue([for c in var.ssh_allowed_cidrs_ipv6 : trimspace(c) != "::/0"])
    error_message = "ssh_allowed_cidrs_ipv6 must not contain ::/0 - SSH open to the internet."
  }
}
