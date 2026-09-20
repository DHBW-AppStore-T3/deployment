# The Forgejo host: the forge itself, its Postgres, and the Actions runner.
#
# This is bootstrap infrastructure — see backend.tf for why its state is local
# while every other environment's lives in the database this host runs.

module "vm" {
  source = "../../modules/openstack_vm"

  name = "ci-dhbw-appstore"
  # "Ubuntu 22.04" no longer exists in this project's image catalog (same
  # finding as envs/staging/main.tf: `openstack image list` against
  # ma_wwi_24sea_appstore_g3 has Ubuntu 24.04 and Ubuntu Server 26.04 LTS, not
  # 22.04 anymore). 24.04 matches staging and appstore-prod-01.
  image      = "Ubuntu 24.04"
  public_key = var.ssh_public_key

  # Smaller than staging's gp1.large. This host runs Forgejo, one Postgres and
  # a single job container at a time (runner/config.yml pins capacity to 1
  # because the Terraform state has no locking across concurrent runs).
  flavor = "gp1.medium"

  # See the NETWORK note in variables.tf. Both are variables rather than
  # literals so the address family is a per-tenant choice.
  network_name     = var.network_name
  connect_via      = var.connect_via
  floating_ip_pool = var.floating_ip_pool

  # Second interface so the forge is reachable without IPv6.
  #
  # Temporarily disabled (both null), same reasoning as envs/staging/main.tf:
  # this OpenStack project (ma_wwi_24sea_appstore_g3) currently has no
  # "DHBWv4" network at all — `openstack network list` shows only DHBWV6 and
  # NAT, so the `data "openstack_networking_network_v2" "secondary"` lookup
  # fails with "Your query returned no results" before Terraform gets to
  # creating anything. Re-set these two to var.secondary_network_name /
  # var.secondary_subnet_name once this project's IPv4 allocation comes back
  # — don't rebuild the feature, the variables and module support are intact.
  secondary_network_name = null
  secondary_subnet_name  = null

  # Referencing the resource rather than a bare name gives Terraform the
  # dependency, so the group and its rules exist before the instance is built.
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
  security_groups = [openstack_networking_secgroup_v2.forgejo_vm.name]

  docker_data_volume_size_gb = var.docker_data_volume_size_gb

  metadata = {
    env  = "forgejo"
    role = "forge"
  }
}

# The Cinder volume is created and attached here, but formatting and mounting
# it at /var/lib/docker is left to Ansible rather than cloud-init.
#
# The module attaches the volume as a separate resource, after the instance
# reports ACTIVE — which is also when cloud-init is already running. Whether
# /dev/vdb exists by the time cloud-init's disk stage runs is a race, and when
# it loses, the setup fails silently: the volume is attached but unused, and
# the symptom only appears later as a full root disk. Ansible runs strictly
# after `terraform apply` returns, so the device is guaranteed to be there.
#
# modules/openstack_vm/variables.tf still describes user_data as the place for
# this. That is accurate for envs that pass their own cloud-init; it is not the
# approach taken here.

output "vm_ip" {
  description = "Address Ansible connects to, selected by connect_via."
  value       = module.vm.vm_ip
}

output "vm_name" {
  value = module.vm.vm_name
}

# The address the A record for the forge's hostname points at.
output "vm_ipv4" {
  value = module.vm.secondary_ipv4
}

# Consumed by the Ansible step that writes the netplan config.
output "vm_ipv4_gateway" {
  value = module.vm.secondary_gateway_ipv4
}

output "vm_ipv4_mac" {
  value = module.vm.secondary_mac
}

output "docker_data_volume_gb" {
  description = "0 when no separate volume was created."
  value       = var.docker_data_volume_size_gb
}