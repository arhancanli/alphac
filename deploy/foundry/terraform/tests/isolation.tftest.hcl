mock_provider "digitalocean" {}

run "foundry_isolation_contract" {
  command = plan

  variables {
    spaces_bucket_prefix = "canli-foundry-ci-contract"
  }

  assert {
    condition = (
      digitalocean_droplet.research.public_networking == false
      && digitalocean_droplet.holdout.public_networking == false
    )
    error_message = "Foundry application Droplets must remain private."
  }

  assert {
    condition = (
      digitalocean_vpc.research.ip_range != digitalocean_vpc.holdout.ip_range
      && digitalocean_vpc.research.name != digitalocean_vpc.holdout.name
    )
    error_message = "Research and holdout must remain on distinct VPCs."
  }

  assert {
    condition = (
      length(digitalocean_database_firewall.foundry.rule) == 1
      && alltrue([
        for rule in digitalocean_database_firewall.foundry.rule : rule.type == "droplet"
      ])
    )
    error_message = "Managed PostgreSQL must trust only the research Droplet."
  }

  assert {
    condition = (
      digitalocean_spaces_bucket.research.acl == "private"
      && digitalocean_spaces_bucket.holdout.acl == "private"
      && digitalocean_spaces_bucket.publication.acl == "private"
    )
    error_message = "Every Foundry bucket must remain private."
  }

  assert {
    condition = (
      length(digitalocean_droplet.bastion) == 0
      && var.enable_ephemeral_bastion == false
    )
    error_message = "The ephemeral bastion must be disabled by default."
  }

  assert {
    condition = (
      strcontains(digitalocean_droplet.research.user_data, "policy drop")
      && strcontains(digitalocean_droplet.research.user_data, "http_access deny all")
      && strcontains(digitalocean_droplet.holdout.user_data, "policy drop")
      && strcontains(digitalocean_droplet.holdout.user_data, "http_access deny all")
    )
    error_message = "Cloud-init must install both host firewall and proxy deny rules."
  }
}
