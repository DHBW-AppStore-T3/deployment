variable "ssh_public_key" {
  description = "SSH public key for the Forgejo host's deploy keypair. Supplied via TF_VAR_ssh_public_key."
  type        = string
}



# Ranges allowed to reach the web UI. Separate from the SSH variables above
# even though the defaults match: the two are independent controls, and sharing
# one variable would make "widen SSH for a moment" silently expose the UI too.
#
# Restricting these means the ACME http-01 and tls-alpn-01 challenges can no
# longer work — the CA has to reach 80/443 from the public internet for either.
# Caddy must use dns-01 on this host, the same way it already does on staging.
variable "web_source_cidr_ipv4" {
  description = "IPv4 range allowed to reach ports 80/443 (DHBW campus / VPN)."
  type        = string
  default     = "141.72.0.0/16"

  validation {
    condition     = can(cidrhost(var.web_source_cidr_ipv4, 0))
    error_message = "web_source_cidr_ipv4 must be a valid IPv4 CIDR, e.g. 141.72.0.0/16."
  }
}

variable "web_source_cidr_ipv6" {
  description = "IPv6 range allowed to reach ports 80/443 (DHBW campus / VPN)."
  type        = string
  default     = "2001:7c0:1b20::/48"

  validation {
    condition     = can(cidrhost(var.web_source_cidr_ipv6, 0))
    error_message = "web_source_cidr_ipv6 must be a valid IPv6 CIDR, e.g. 2001:7c0:1b20::/48."
  }
}

# NETWORK
#
# connect_via selects one of three ways to reach the host — IPv4 or IPv6, with
# a fixed address or a floating one:
#
#   fixed_ipv4     the instance's fixed IPv4, for networks whose IPv4 range is
#                  publicly routable 
#   fixed_ipv6     the instance's fixed IPv6
#   floating_ipv4  a floating IP drawn from floating_ip_pool, for networks
#                  whose fixed IPv4 is private
#
# IPv6 is selected here, matching envs/staging. Anyone deploying this on their
# own OpenStack chooses the network and address family that suit their tenant;
# the variables below are the only place that changes.
#
# Whatever is chosen, the host must be able to reach the staging VM — the
# runner's job containers connect to it over SSH from here.
variable "network_name" {
  description = "OpenStack network the Forgejo host attaches to."
  type        = string
  default     = "DHBWV6"
}

variable "secondary_network_name" {
  description = "Second network for dual-stack. null = single-homed."
  type        = string
  default     = "DHBWv4"
}

# DHBWv4 has two IPv4 subnets, The -188 one
# is where the platform's Apps land, so the forge keeps them company.
variable "secondary_subnet_name" {
  description = "IPv4 subnet within secondary_network_name."
  type        = string
  default     = "DHBWv4-188"
}

variable "connect_via" {
  description = "Which address Ansible connects to. See modules/openstack_vm/variables.tf."
  type        = string
  default     = "fixed_ipv6"

  validation {
    condition     = contains(["fixed_ipv4", "fixed_ipv6", "floating_ipv4"], var.connect_via)
    error_message = "connect_via must be \"fixed_ipv4\", \"fixed_ipv6\", or \"floating_ipv4\"."
  }
}

variable "floating_ip_pool" {
  description = "External network to allocate a floating IP from. Only used when connect_via = \"floating_ipv4\"."
  type        = string
  default     = ""
}

# Sized for what actually accumulates on this host, none of which is on the
# staging VM: the Forgejo git repositories, the Postgres holding both the
# forgejo and terraform_state databases, and the deploy job image — node plus
# Terraform, Ansible and Trivy runs to several hundred MB on its own, and a new
# layer set is written every time job-image/Dockerfile changes.
#
# envs/staging sets this to 0 and keeps everything on the root disk. That is
# fine for a host whose containers are pulled and discarded; it is not fine for
# the host that stores the state of every other environment.
variable "docker_data_volume_size_gb" {
  description = "Cinder volume for /var/lib/docker. 0 disables it."
  type        = number
  default     = 50
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
