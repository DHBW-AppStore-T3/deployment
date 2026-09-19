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

  security_groups = ["default", openstack_networking_secgroup_v2.appstore_vm.name]

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
