terraform {
  required_version = ">= 1.5.0"

  # Same pg backend as envs/staging, own schema. conn_str comes from the
  # PG_CONN_STR environment variable (Terraform's pg backend reads it
  # automatically when conn_str isn't set in the block) — the self-hosted
  # runner container (infrastructure/runner-vm/docker-compose.yml) sets it,
  # pointing at the tfstate-postgres it runs alongside itself.
  backend "pg" {
    schema_name = "production"
  }

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.4"
    }
  }
}
