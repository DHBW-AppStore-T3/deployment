# Hermes VM — dedicated host for hermes-agent, split off appstore-prod-01
# (deployment#49). Previously hermes-agent ran as an overlay on
# appstore-prod-01 itself (docker-compose.agent.yml); appstore-prod-01 has
# since been fully wiped of that overlay (verified via SSH: no containers,
# no volumes, no systemd units — only the unused compose file, removed in
# this same change). This is a from-scratch rebuild on a new host, not a
# live cutover.
#
# Small and SSH-only by design: this VM runs one lightweight agent
# container and reaches podman-mcp on the three target VMs outbound over
# MCP/TCP (HARNESS.md System 3.2 — no SSH access for agents, only for
# humans). It serves nothing inbound itself, hence no HTTP/HTTPS rules in
# security_group.tf, unlike envs/staging and envs/production.

module "vm" {
  source = "../../modules/openstack_vm"

  name       = "hermes-dhbw-appstore"
  image      = "Ubuntu 24.04"
  flavor     = "gp1.large"
  public_key = var.ssh_public_key

  # Same DHBWv4-unavailable situation as envs/staging and envs/production —
  # this OpenStack project only has DHBWV6 and NAT right now.
  network_name           = "DHBWV6"
  connect_via            = "fixed_ipv6"
  secondary_network_name = null
  secondary_subnet_name  = null

  security_groups = [openstack_networking_secgroup_v2.appstore_vm.name]

  # hermes-agent's own state (hermes_agent_data volume) is small — no
  # container images being built or pulled at any real scale here, unlike
  # staging/production. Root disk is enough; no separate Cinder volume.
  docker_data_volume_size_gb = 0

  metadata = {
    env  = "hermes"
    role = "agent"
  }
}

output "vm_ip" {
  value = module.vm.vm_ip
}

output "vm_name" {
  value = module.vm.vm_name
}
