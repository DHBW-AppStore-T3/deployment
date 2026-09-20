# Security group for the staging VM.
#
# Previously this was referenced by name only ("appstore-deploy") and had to be
# created by hand in the tenant — an undocumented prerequisite that made a fresh
# apply fail with a confusing "security group not found". Creating it here makes
# the environment self-contained.
#
# WHAT IS DELIBERATELY NOT OPENED
# docker-compose.staging.yml publishes Postgres (5432), RabbitMQ (5672) and the
# RabbitMQ management UI (15672) on the host. The VM's fixed IP is publicly
# routable on this OpenStack (see infrastructure/README.md), so this security
# group is the ONLY thing keeping those services off the internet. Do not add
# rules for them — use an SSH tunnel if you need access.

resource "openstack_networking_secgroup_v2" "appstore_vm" {
  # We enforce a unique security-group for this vm
  name        = "staging-dhbw-appstore-sg"
  description = "Staging Docker host: SSH for Ansible, HTTP/HTTPS for the app"

  # delete_default_rules stays false, so the group keeps OpenStack's default
  # allow-all egress. The VM needs outbound access for apt, GHCR and Galaxy.
}

resource "openstack_networking_secgroup_rule_v2" "ssh" {
  for_each          = toset(var.ssh_allowed_cidrs_ipv4)
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  # Scoped to an allow-list; the scanner cannot see that the list is
  # bounded, only that a prefix is wider than one host. 0.0.0.0/0 is
  # rejected at plan time by the variable validation.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = each.value
  description      = "SSH for the Ansible deploy step (campus IPv4)"
}

# OpenStack security-group rules are per-ethertype: the IPv4 rules in this file
# do not filter IPv6 traffic at all. Without this rule, an IPv6-reachable VM
# would have port 22 governed by nothing here.
resource "openstack_networking_secgroup_rule_v2" "ssh_v6" {
  for_each          = toset(var.ssh_allowed_cidrs_ipv6)
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  # Scoped to an allow-list; the scanner cannot see that the list is
  # bounded, only that a prefix is wider than one host. ::/0 is rejected
  # at plan time by the variable validation.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = each.value
  description      = "SSH: CI runner + operator VPN only (IPv6)"
}

resource "openstack_networking_secgroup_rule_v2" "http" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  # Public on purpose: this is the web entrypoint, and 80 also carries the
  # ACME challenge.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = "0.0.0.0/0"
  description      = "HTTP - redirected to HTTPS, and the ACME challenge"
}

resource "openstack_networking_secgroup_rule_v2" "https" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  # Public on purpose: this is the web entrypoint. TLS terminates at Caddy.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = "0.0.0.0/0"
  description      = "HTTPS - the application"
}

# The application is meant to be publicly reachable, so 80/443 stay open to
# everyone on both ethertypes. Only SSH is campus-restricted.
resource "openstack_networking_secgroup_rule_v2" "http_v6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 80
  port_range_max    = 80
  # Public on purpose: this is the web entrypoint, and 80 also carries the
  # ACME challenge.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = "::/0"
  description      = "HTTP - redirected to HTTPS, and the ACME challenge (IPv6)"
}

# ICMPv6 is not optional the way ICMP is on IPv4: Path MTU Discovery relies on
# "Packet Too Big" messages, and blocking them creates MTU black holes where a
# connection establishes but larger transfers hang - a TLS handshake that
# succeeds while the response never arrives. RFC 4890 advises against filtering
# ICMPv6 wholesale. It also makes the host pingable, which is worth something
# when the only way in is IPv6.
resource "openstack_networking_secgroup_rule_v2" "icmpv6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "ipv6-icmp"
  # ICMPv6 carries Neighbour Discovery and Router Advertisements, so
  # filtering it stops IPv6 working at all (RFC 4890). Not a port.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = "::/0"
  description      = "ICMPv6 - required for Path MTU Discovery (RFC 4890)"
}

resource "openstack_networking_secgroup_rule_v2" "https_v6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 443
  port_range_max    = 443
  # Public on purpose: this is the web entrypoint. TLS terminates at Caddy.
  #trivy:ignore:openstack-networking-no-public-ingress
  remote_ip_prefix = "::/0"
  description      = "HTTPS - the application (IPv6)"
}
