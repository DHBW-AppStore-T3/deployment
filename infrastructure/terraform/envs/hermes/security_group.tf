# Security group for the Hermes VM.
#
# SSH only — no HTTP/HTTPS. This host serves nothing inbound: hermes-agent
# talks outbound to Discord and to the three podman-mcp instances (prod,
# staging, ci) on TCP 8080, and the loopback-only dashboard is reached via
# SSH port-forward, same as the current appstore-prod-01 overlay. See
# main.tf's header comment.

resource "openstack_networking_secgroup_v2" "appstore_vm" {
  name        = "hermes-dhbw-appstore-sg"
  description = "Hermes agent host: SSH only, no inbound application traffic"
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

# OpenStack security-group rules are per-ethertype: the IPv4 rule above does
# not filter IPv6 traffic at all. Without this rule, an IPv6-reachable VM
# would have port 22 governed by nothing here.
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

# See envs/staging/security_group.tf for the RFC 4890 rationale.
resource "openstack_networking_secgroup_rule_v2" "icmpv6" {
  security_group_id = openstack_networking_secgroup_v2.appstore_vm.id
  direction         = "ingress"
  ethertype         = "IPv6"
  protocol          = "ipv6-icmp"
  remote_ip_prefix  = "::/0"
  description       = "ICMPv6 - required for Path MTU Discovery (RFC 4890)"
}
