# Module is used to define things in one place
# and achieve DRY
module "vm" {
  source = "../../modules/openstack_vm"

  name = "staging-dhbw-appstore"
  # "Ubuntu 22.04" doesn't exist in this project's image catalog
  # (`openstack image list` against ma_wwi_24sea_appstore_g3: Cirros,
  # Debian 13, Rocky 10.1, Ubuntu 24.04, Ubuntu Server 26.04 LTS,
  # Windows variants) — Terraform failed with "Unable to find image
  # with name Ubuntu 22.04". Ubuntu 24.04 is what appstore-prod-01
  # itself runs (`openstack server show appstore-prod-01`), so this
  # keeps staging on the same base OS as prod rather than picking
  # something newer/different.
  image      = "Ubuntu 24.04"
  flavor     = "gp1.large"
  public_key = var.ssh_public_key

  # IPv6 works here only because the certificate is obtained over dns-01.
  # The CA cannot reach this host inbound: its own endpoint has no AAAA record,
  # and both inbound challenge types failed against DHBWV6:
  #
  #   http-01      "Could not fetch URL: http://.../.well-known/acme-challenge/..."
  #   tls-alpn-01  "Unable to retrieve server certificate for ..."
  #
  # dns-01 needs no inbound connection at all: Caddy writes a TXT record over
  # RFC 2136 and the CA reads it from DNS. See caddy/Caddyfile.
  #
  # Reachability itself was never the issue - a host outside the DHBW network
  # reached this VM over IPv6 on both 80 and 443.
  network_name = "DHBWV6"
  connect_via  = "fixed_ipv6"

  # Second interface so clients without IPv6 can reach the app. Ansible connects
  # over IPv6 as before; only the A record is new.
  #
  # Temporarily disabled (both null): this OpenStack project
  # (ma_wwi_24sea_appstore_g3) currently has no "DHBWv4" network at all —
  # `openstack network list` shows only DHBWV6 and NAT, so the `data
  # "openstack_networking_network_v2" "secondary"` lookup in the module
  # fails with "Your query returned no results" before Terraform ever
  # gets to creating anything. appstore-prod-01 is IPv6-only for the same
  # reason. The module keeps full dual-stack support (see
  # secondary_network.tf) for whenever this project's IPv4 allocation
  # comes back — re-set these two to "DHBWv4"/"DHBWv4-188" then, don't
  # rebuild the feature.
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
  security_groups = [openstack_networking_secgroup_v2.appstore_vm.name]

  # Belongs at 50, the way the Forgejo host has it: the named volumes under
  # /var/lib/docker hold both databases, and a volume also survives a
  # replacement of the instance.
  #
  # Was 0 because an earlier attempt hung in "creating" and made every apply
  # wait out its ten-minute timeout. Verified directly against this project's
  # Cinder before re-enabling: `openstack volume create --size 1` now reaches
  # "available" within 15s, not stuck — the outage that caused the original
  # attempt to hang is over. Confirmed necessary, not just theoretical: the
  # first real Moodle-enabled deploy ran the 10GB root disk out of space
  # entirely (`no space left on device` mid-pull, moodlehq/moodle-php-apache
  # alone is a large image on top of the existing stack).
  docker_data_volume_size_gb = 50

  metadata = {
    env  = "staging"
    role = "docker"
  }
}

output "vm_ip" {
  value = module.vm.vm_ip
}

# The address the A record for APP_HOSTNAME points at.
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
