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
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv4"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.ssh_source_cidr_ipv4
  description       = "SSH for the Ansible deploy step (campus IPv4)"
}

resource "openstack_networking_secgroup_rule_v2" "ssh_v6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "tcp"
  port_range_min    = 22
  port_range_max    = 22
  remote_ip_prefix  = var.ssh_source_cidr_ipv6
  description       = "SSH for the Ansible deploy step (campus IPv6)"
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
