terraform {
  required_version = ">= 1.5.0"

  # Same pg backend as envs/staging and envs/production, own schema.
  # conn_str comes from PG_CONN_STR in the environment (Terraform's pg
  # backend reads it automatically when conn_str isn't set in the block).
  backend "pg" {
    schema_name = "hermes"
  }

  required_providers {
    openstack = {
      source  = "terraform-provider-openstack/openstack"
      version = "~> 3.4"
    }
  }
}
