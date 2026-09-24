# Security group for the production VM.
#
# Named distinctly from the existing hand-created "appstore-prod" group
# (still attached to the current, hand-built appstore-prod-01) to avoid the
# exact "Multiple security_group matches found" conflict envs/staging hit
# when two groups shared a name — the old group is deleted once the old VM
# is decommissioned, at which point this could be renamed, but there's no
# need to.
#
# WHAT IS DELIBERATELY NOT OPENED: docker-compose.prod.yml does not publish
# Postgres/RabbitMQ/Redis ports on the host interface the way some dev
# tooling might expect — only 80/443 (nginx) are meant to be public. Do not
# add rules for the internal services; use an SSH tunnel for debugging.

resource "openstack_networking_secgroup_v2" "appstore_vm" {
  name        = "appstore-prod-01-sg"
  description = "Production Docker host: SSH for Ansible, HTTP/HTTPS for the app"
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  for_each          = toset(var.ssh_allowed_cidrs_ipv4)
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = each.value
  description       = "SSH for the Ansible deploy step (campus IPv4)"
}

resource "openstack_networking_secgroup_rule_v2" "ssh_v6" {
  for_each          = toset(var.ssh_allowed_cidrs_ipv6)
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = each.value
  description       = "SSH: CI runner + operator VPN only (IPv6)"
}

resource "openstack_networking_secgroup_rule_v2" "http" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "0.0.0.0/0"
  description       = "HTTP - redirected to HTTPS, and the ACME challenge"
}

resource "openstack_networking_secgroup_rule_v2" "https" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  remote_ip_prefix  = "0.0.0.0/0"
  description       = "HTTPS - the application"
}

resource "openstack_networking_secgroup_rule_v2" "http_v6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  remote_ip_prefix  = "::/0"
  description       = "HTTP - redirected to HTTPS, and the ACME challenge (IPv6)"
}

resource "openstack_networking_secgroup_rule_v2" "https_v6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  remote_ip_prefix  = "::/0"
  description       = "HTTPS - the application (IPv6)"
}

# See envs/staging/security_group.tf for the RFC 4890 rationale.
resource "openstack_networking_secgroup_rule_v2" "icmpv6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "ipv6-icmp"
  remote_ip_prefix  = "::/0"
  description       = "ICMPv6 - required for Path MTU Discovery (RFC 4890)"
}

# deployment#49 — podman-mcp on this host is reachable only from the Hermes
# VM, scoped to its single IPv6 address rather than a published port open to
# the tenant network. docker-compose.podman-mcp.yml publishes 8080 on the
# host interface; this rule is the only thing keeping it off everyone else,
# the same pattern as the "WHAT IS DELIBERATELY NOT OPENED" note above.
resource "openstack_networking_secgroup_rule_v2" "podman_mcp_from_hermes" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 8080
  port_range_max    = 8080
  remote_ip_prefix  = "${var.hermes_vm_ipv6}/128"
  description       = "podman-mcp - Hermes agent only"
}
