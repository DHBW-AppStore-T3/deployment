# Production VM — first-ever Terraform-managed generation.
#
# Previously appstore-prod-01 was hand-built (see docs/prod-setup.md) and its
# only SSH access was one operator's personal key. When that key stopped being
# available there was no way back in. This env brings production onto the same
# IaC pattern as envs/staging: Terraform registers its own keypair from
# TF_VAR_ssh_public_key, so access is never tied to a laptop that might
# disappear.
#
# Flavor/image match the original hand-built appstore-prod-01
# (`openstack server show appstore-prod-01`: general.medium, Ubuntu 24.04).

module "vm" {
  source = "../../modules/openstack_vm"

  name       = "appstore-prod-01"
  image      = "Ubuntu 24.04"
  flavor     = "general.medium"
  public_key = var.ssh_public_key

  # Same DHBWv4-unavailable situation as envs/staging and envs/forgejo — this
  # OpenStack project only has DHBWV6 and NAT right now. Re-set to
  # "DHBWv4"/"DHBWv4-188" once the project's IPv4 allocation comes back.
  network_name           = "DHBWV6"
  connect_via            = "fixed_ipv6"
  secondary_network_name = null
  secondary_subnet_name  = null

  # This host's own group only. It previously also carried the tenant-wide
  # "default" group, whose single ingress rule admits any other member of
  # "default" on every port - so membership alone granted full access
  # between any two instances that happened to share it, regardless of the
  # scoped rules below.
  #
  # Nothing here needed it: egress is covered because this group keeps
  # OpenStack's default allow-all egress (delete_default_rules is false),
  # SSH and HTTP/HTTPS are explicit, and no host-to-host traffic exists
  # between the control-plane hosts other than the deploy's own SSH.
  security_groups = [openstack_networking_secgroup_v2.appstore_vm.name]

  # Same reasoning as staging/forgejo: a named volume for /var/lib/docker
  # survives an instance replacement, and the root disk alone ran a staging
  # deploy out of space once already (see infrastructure/README.md).
  docker_data_volume_size_gb = 50

  metadata = {
    env  = "production"
    role = "docker"
  }
}

output "vm_ip" {
  value = module.vm.vm_ip
}

output "vm_name" {
  value = module.vm.vm_name
}
