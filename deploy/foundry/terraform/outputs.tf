output "project_id" {
  value = digitalocean_project.foundry.id
}

output "research_node_private_ip" {
  value = digitalocean_droplet.research.ipv4_address_private
}

output "holdout_node_private_ip" {
  value = digitalocean_droplet.holdout.ipv4_address_private
}

output "database_private_host" {
  value     = digitalocean_database_cluster.foundry.private_host
  sensitive = true
}

output "database_port" {
  value = digitalocean_database_cluster.foundry.port
}

output "nat_gateway_ids" {
  value = {
    research = digitalocean_vpc_nat_gateway.research.id
    holdout  = digitalocean_vpc_nat_gateway.holdout.id
  }
}

output "bucket_names" {
  value = {
    research    = digitalocean_spaces_bucket.research.name
    holdout     = digitalocean_spaces_bucket.holdout.name
    publication = digitalocean_spaces_bucket.publication.name
  }
}

output "acceptance_state" {
  value = "PROVISIONED_UNVERIFIED"
}
