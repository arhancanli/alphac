locals {
  research_bucket    = "${var.spaces_bucket_prefix}-research"
  holdout_bucket     = "${var.spaces_bucket_prefix}-holdout"
  publication_bucket = "${var.spaces_bucket_prefix}-publication"
}

resource "digitalocean_vpc" "research" {
  name     = "canli-foundry-research"
  region   = var.region
  ip_range = var.research_vpc_cidr
}

resource "digitalocean_vpc" "holdout" {
  name     = "canli-foundry-holdout"
  region   = var.region
  ip_range = var.holdout_vpc_cidr
}

resource "digitalocean_vpc_nat_gateway" "research" {
  name   = "canli-foundry-research-egress"
  type   = "PUBLIC"
  region = var.region
  size   = "1"

  vpcs {
    vpc_uuid        = digitalocean_vpc.research.id
    default_gateway = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_vpc_nat_gateway" "holdout" {
  name   = "canli-foundry-holdout-egress"
  type   = "PUBLIC"
  region = var.region
  size   = "1"

  vpcs {
    vpc_uuid        = digitalocean_vpc.holdout.id
    default_gateway = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_tag" "research" {
  name = "canli-foundry-research"
}

resource "digitalocean_tag" "holdout" {
  name = "canli-foundry-holdout"
}

resource "digitalocean_droplet" "research" {
  name              = "canli-foundry-research-01"
  region            = var.region
  size              = var.research_node_size
  image             = "ubuntu-24-04-x64"
  vpc_uuid          = digitalocean_vpc.research.id
  public_networking = false
  ipv6              = false
  monitoring        = true
  backups           = true
  graceful_shutdown = true
  droplet_agent     = true
  ssh_keys          = var.operator_ssh_key_fingerprints
  tags              = [digitalocean_tag.research.id]
  user_data = templatefile("${path.module}/cloud-init/research.yaml.tftpl", {
    nftables_config = file("${path.module}/../host/research.nft")
    squid_config    = file("${path.module}/../host/squid-foundry.conf")
  })

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [digitalocean_vpc_nat_gateway.research]
}

resource "digitalocean_droplet" "holdout" {
  name              = "canli-foundry-holdout-01"
  region            = var.region
  size              = var.holdout_node_size
  image             = "ubuntu-24-04-x64"
  vpc_uuid          = digitalocean_vpc.holdout.id
  public_networking = false
  ipv6              = false
  monitoring        = true
  backups           = true
  graceful_shutdown = true
  droplet_agent     = true
  ssh_keys          = var.operator_ssh_key_fingerprints
  tags              = [digitalocean_tag.holdout.id]
  user_data = templatefile("${path.module}/cloud-init/holdout.yaml.tftpl", {
    nftables_config = file("${path.module}/../host/holdout.nft")
    squid_config    = file("${path.module}/../host/squid-holdout.conf")
  })

  lifecycle {
    prevent_destroy = true
  }

  depends_on = [digitalocean_vpc_nat_gateway.holdout]
}

resource "digitalocean_droplet" "bastion" {
  count = var.enable_ephemeral_bastion ? 1 : 0

  name              = "canli-foundry-bastion-ephemeral"
  region            = var.region
  size              = "s-1vcpu-1gb"
  image             = "ubuntu-24-04-x64"
  vpc_uuid          = digitalocean_vpc.research.id
  public_networking = true
  ipv6              = false
  monitoring        = true
  backups           = false
  graceful_shutdown = true
  droplet_agent     = true
  ssh_keys          = var.operator_ssh_key_fingerprints
  tags              = [digitalocean_tag.research.id]
  user_data         = file("${path.module}/cloud-init/bastion.yaml")
}

resource "digitalocean_database_cluster" "foundry" {
  name                 = "canli-foundry-postgres"
  engine               = "pg"
  version              = var.postgres_version
  size                 = var.postgres_size
  region               = var.region
  node_count           = 1
  private_network_uuid = digitalocean_vpc.research.id
  project_id           = digitalocean_project.foundry.id
  tags                 = [digitalocean_tag.research.id]

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_database_db" "foundry" {
  cluster_id = digitalocean_database_cluster.foundry.id
  name       = "foundry"
}

resource "digitalocean_database_firewall" "foundry" {
  cluster_id = digitalocean_database_cluster.foundry.id

  rule {
    type  = "droplet"
    value = digitalocean_droplet.research.id
  }
}

resource "digitalocean_spaces_bucket" "research" {
  name          = local.research_bucket
  region        = var.region
  acl           = "private"
  force_destroy = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    id                                     = "abort-incomplete-uploads"
    enabled                                = true
    prefix                                 = ""
    abort_incomplete_multipart_upload_days = 7

    noncurrent_version_expiration {
      days = 3650
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_spaces_bucket" "holdout" {
  name          = local.holdout_bucket
  region        = var.region
  acl           = "private"
  force_destroy = false

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_spaces_bucket" "publication" {
  name          = local.publication_bucket
  region        = var.region
  acl           = "private"
  force_destroy = false

  versioning {
    enabled = true
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "digitalocean_firewall" "research" {
  name        = "canli-foundry-research-deny-default"
  droplet_ids = [digitalocean_droplet.research.id]

  dynamic "inbound_rule" {
    for_each = var.enable_ephemeral_bastion ? [1] : []
    content {
      protocol           = "tcp"
      port_range         = "22"
      source_droplet_ids = [digitalocean_droplet.bastion[0].id]
    }
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "25060"
    destination_addresses = [var.research_vpc_cidr]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "443"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "123"
    destination_addresses = ["0.0.0.0/0"]
  }
}

resource "digitalocean_firewall" "holdout" {
  name        = "canli-foundry-holdout-deny-default"
  droplet_ids = [digitalocean_droplet.holdout.id]

  outbound_rule {
    protocol              = "tcp"
    port_range            = "443"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "123"
    destination_addresses = ["0.0.0.0/0"]
  }
}

resource "digitalocean_firewall" "bastion" {
  count = var.enable_ephemeral_bastion ? 1 : 0

  name        = "canli-foundry-bastion-ephemeral"
  droplet_ids = [digitalocean_droplet.bastion[0].id]

  inbound_rule {
    protocol         = "tcp"
    port_range       = "22"
    source_addresses = [var.operator_cidr]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "22"
    destination_addresses = [var.research_vpc_cidr]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "443"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "53"
    destination_addresses = ["0.0.0.0/0"]
  }

  outbound_rule {
    protocol              = "udp"
    port_range            = "123"
    destination_addresses = ["0.0.0.0/0"]
  }
}

resource "digitalocean_project" "foundry" {
  name        = var.project_name
  description = "Isolated ALPHAC bounded research, replay and sanitized publication infrastructure."
  purpose     = "Operational / Developer tooling"
  environment = "Production"
  is_default  = false
  resources = concat(
    [
      digitalocean_droplet.research.urn,
      digitalocean_droplet.holdout.urn,
      digitalocean_spaces_bucket.research.urn,
      digitalocean_spaces_bucket.holdout.urn,
      digitalocean_spaces_bucket.publication.urn,
    ],
    var.enable_ephemeral_bastion ? [digitalocean_droplet.bastion[0].urn] : [],
  )
}
